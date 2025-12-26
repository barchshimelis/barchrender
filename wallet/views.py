from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Sum, Q
from django.http import JsonResponse
from django.db import transaction

from accounts.models import CustomUser
from balance.utils import get_wallet_balance, update_wallet_balance
from balance.models import Wallet
from commission.models import CommissionSetting
from products.models import UserProductTask
from products.utils import get_daily_task_limit
from stoppoints.models import StopPoint, StopPointProgress
from .models import CRYPTO_NETWORK_CHOICES, UserWalletAddress, UserWithdrawal, WithdrawalConfig
from .utils import reset_user_cycle_state
from notification.utils import notify_roles, create_admin_dashboard_event

@login_required
def wallet_management_view(request):
    user = request.user
    wallet_address = UserWalletAddress.objects.filter(user=user).first()
    
    # Get wallet for balance calculation
    from balance.models import Wallet
    wallet = Wallet.objects.get_or_create(user=user)[0]
    
    # Calculate total withdrawable balance (after completing all tasks)
    completed_tasks_count = UserProductTask.objects.filter(
        user=user, is_completed=True
    ).count()
    daily_limit = get_daily_task_limit(user)
    tasks_completed = completed_tasks_count >= daily_limit
    
    # Available to withdraw is based on cumulative_total (recharge + commissions - approved withdrawals)
    # This is the user's withdrawable asset ledger, separate from the spendable task balance
    total_asset = wallet.cumulative_total
    
    config = WithdrawalConfig.get_config()

    # Get withdrawal history
    withdrawal_history = UserWithdrawal.objects.filter(user=user).order_by('-created_at')[:10]
    
    # Calculate today's total withdrawals
    today = timezone.now().date()
    today_withdrawals = UserWithdrawal.objects.filter(
        user=user,
        created_at__date=today,
        status__in=['PENDING', 'PROCESSING', 'APPROVED']
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Handle form submissions
    if request.method == "POST":
        # Handle Wallet Binding
        if 'bind_wallet' in request.POST:
            # Prevent users from changing wallet after first binding
            if wallet_address:
                messages.error(
                    request,
                    "❌ You cannot change your wallet address once bound. "
                    "Please contact customer service if you need to update it."
                )
                return redirect("wallet:manage")
            
            if not tasks_completed:
                messages.error(
                    request,
                    f"You must complete all {daily_limit} tasks before binding your wallet. "
                    f"Completed: {completed_tasks_count}"
                )
            else:
                address = request.POST.get("address", "").strip()
                default_network = CRYPTO_NETWORK_CHOICES[0][0] if CRYPTO_NETWORK_CHOICES else "TRX-20"

                if not address:
                    messages.error(request, "Wallet address is required.")
                elif UserWalletAddress.objects.filter(address=address).exclude(user=user).exists():
                    messages.error(request, "This wallet address is already linked to another account.")
                else:
                    chosen_network = default_network
                    # Create wallet (only once)
                    UserWalletAddress.objects.create(
                        user=user,
                        address=address,
                        network=chosen_network
                    )
                    if wallet:
                        wallet.info_alert_wallet = True
                        wallet.save(update_fields=["info_alert_wallet"])
                    create_admin_dashboard_event(
                        user=user,
                        event_type="wallet_bind",
                        message=f"{user.username} bound a wallet address.",
                        metadata={
                            "network": chosen_network,
                            "address": address,
                            "event": "wallet_bind",
                        },
                    )
                    messages.success(request, "✅ Wallet bound successfully! This address is now permanent.")
                    return redirect("wallet:manage")

        # Handle Withdrawal with Enhanced Validation
        elif 'withdraw' in request.POST:
            if not wallet_address:
                messages.error(request, "You must bind your wallet before making a withdrawal.")
                return redirect("wallet:manage")
            
            # Check if all tasks are completed
            if not tasks_completed:
                messages.error(
                    request,
                    f"You must complete all {daily_limit} tasks before withdrawing. "
                    f"Completed: {completed_tasks_count}/{daily_limit}"
                )
                return redirect("wallet:manage")

            network = request.POST.get("network")
            fund_password = request.POST.get("fund_password")
            withdraw_amount_str = request.POST.get("amount", "").strip()
            withdraw_all = request.POST.get("withdraw_all", "")

            # Basic validation
            if not user.is_superuser:
                # Check if fund password is plain text (not hashed) and hash it
                if user.fund_password and not user.fund_password.startswith(('pbkdf2_sha256$', 'bcrypt$', 'sha1$')):
                    # This is plain text, hash it
                    user.set_fund_password(user.fund_password)
                    print(f"Fixed plain text fund password for user {user.username}")
                
                if not user.check_fund_password(fund_password):
                    messages.error(request, "Invalid fund password.")
                    return redirect("wallet:manage")
            
            if not network:
                messages.error(request, "Please select a network protocol.")
                return redirect("wallet:manage")
            
            # Handle withdraw all option
            if withdraw_all:
                # Withdraw the entire withdrawable ledger
                withdraw_amount = total_asset
                if withdraw_amount <= 0:
                    messages.error(
                        request,
                        "Insufficient balance for withdrawal."
                    )
                    return redirect("wallet:manage")
                # NOTE: Do not change wallet balances here. Deduction happens only on admin approval.
            else:
                # Parse and validate withdrawal amount
                try:
                    withdraw_amount = Decimal(withdraw_amount_str)
                except (ValueError, TypeError):
                    messages.error(request, "Please enter a valid withdrawal amount.")
                    return redirect("wallet:manage")
                
                # Validate amount is positive
                if withdraw_amount <= 0:
                    messages.error(request, "Withdrawal amount must be greater than zero.")
                    return redirect("wallet:manage")
                
                if withdraw_amount > total_asset:
                    messages.error(
                        request,
                        f"You cannot withdraw more than your available balance of ${total_asset}."
                    )
                    return redirect("wallet:manage")
            
            # Check minimum withdrawal
            if withdraw_amount < config.min_withdrawal:
                messages.error(
                    request,
                    f"Minimum withdrawal amount is ${config.min_withdrawal}."
                )
                return redirect("wallet:manage")
            
            # Check maximum withdrawal per transaction
            if withdraw_amount > config.max_withdrawal:
                messages.error(
                    request,
                    f"Maximum withdrawal amount per transaction is ${config.max_withdrawal}."
                )
                return redirect("wallet:manage")
            
            # Calculate fee
            fee_amount = (withdraw_amount * config.get_fee_percent(network) / 100).quantize(Decimal("0.01"))
            net_amount = withdraw_amount - fee_amount
            
            # Check daily withdrawal limit
            if today_withdrawals + withdraw_amount > config.daily_withdrawal_limit:
                remaining = config.daily_withdrawal_limit - today_withdrawals
                messages.error(
                    request,
                    f"Daily withdrawal limit exceeded. You can withdraw up to ${remaining} more today."
                )
                return redirect("wallet:manage")
            
            # Check for pending withdrawals (optional: limit concurrent pending withdrawals)
            pending_count = UserWithdrawal.objects.filter(
                user=user,
                status='PENDING'
            ).count()
            
            if pending_count >= 3:  # Max 3 pending withdrawals at a time
                messages.error(
                    request,
                    "You have too many pending withdrawal requests. "
                    "Please wait for admin approval before submitting more."
                )
                return redirect("wallet:manage")
            
            # All validations passed - create withdrawal request
            try:
                # Create withdrawal record (balance will be deducted on approval)
                withdrawal = UserWithdrawal.objects.create(
                    user=user,
                    amount=withdraw_amount,
                    fee_amount=Decimal('0.00'),  # No fees
                    net_amount=withdraw_amount,  # Full amount goes to user
                    network=network,
                    wallet_address=wallet_address.address,
                    balance_at_request=total_asset,
                    status="PENDING"
                )

                notify_roles(
                    roles=("customerservice",),
                    title="New withdrawal request",
                    message=f"{user.username} requested a ${withdraw_amount} withdrawal via {network}.",
                    category="withdraw_request",
                    metadata={
                        "username": user.username,
                        "amount": str(withdraw_amount),
                        "network": network,
                        "wallet_address": wallet_address.address,
                        "event": "withdraw_request",
                        "status": "pending",
                        "withdrawal_id": withdrawal.id,
                    }
                )
                create_admin_dashboard_event(
                    user=user,
                    event_type="withdraw_request",
                    message=f"{user.username} requested a withdrawal of ${withdraw_amount} via {network}.",
                    metadata={
                        "amount": str(withdraw_amount),
                        "network": network,
                        "event": "withdraw_request",
                        "status": "pending",
                    },
                )
                
                messages.success(
                    request,
                    f"Withdrawal request submitted successfully! " 
                    f"Amount: ${withdraw_amount}"
                )
                return redirect("wallet:manage")
            
            except Exception as e:
                messages.error(request, f"An error occurred while processing your withdrawal: {str(e)}")
                return redirect("wallet:manage")

    # Prepare context for template
    available_to_withdraw = total_asset  # Full total balance is available for withdrawal
    daily_remaining = max(config.daily_withdrawal_limit - today_withdrawals, Decimal('0.00'))
    
    context = {
        "wallet_address": wallet_address,
        "wallet": wallet,  # Balance wallet object
        "total_asset": total_asset,
        "balance": total_asset,  # For backward compatibility in template
        "current_balance": wallet.current_balance,
        "product_commission": wallet.product_commission,
        "referral_commission": wallet.referral_commission,
        "referral_earned_balance": wallet.referral_earned_balance,
        "networks": CRYPTO_NETWORK_CHOICES,
        "config": config,
        "tasks_completed": tasks_completed,
        "completed_tasks_count": completed_tasks_count,
        "daily_limit": daily_limit,
        "withdrawal_history": withdrawal_history,
        "available_to_withdraw": available_to_withdraw,
        "today_withdrawals": today_withdrawals,
        "daily_remaining": daily_remaining,
    }
    
    return render(request, "wallet/wallet_management.html", context)

@login_required
@user_passes_test(lambda u: u.is_authenticated and u.role in ['admin', 'superadmin'])
def approve_withdrawal(request, withdrawal_id):
    """Approve a withdrawal request and deduct user wallet balance"""
    with transaction.atomic():
        # Lock the withdrawal record
        withdrawal = get_object_or_404(
            UserWithdrawal.objects.select_for_update(),
            id=withdrawal_id,
            status__in=["PENDING", "PROCESSING"]
        )

        # Lock the user's wallet
        wallet = Wallet.objects.select_for_update().get(user=withdrawal.user)
        config = WithdrawalConfig.get_config()

        # Ensure there is enough withdrawable balance (cumulative ledger)
        available_balance = wallet.cumulative_total
        if available_balance < withdrawal.amount:
            messages.error(
                request,
                f"Cannot approve withdrawal: Insufficient withdrawable balance. "
                f"Required: ${withdrawal.amount}, Available: ${available_balance}"
            )
            return redirect("accounts:admin_dashboard")

        # Deduct only from the withdrawable ledger (keep current_balance for task operations)
        wallet.cumulative_total = available_balance - withdrawal.amount
        wallet.product_commission = Decimal("0.00")
        wallet.referral_commission = Decimal("0.00")
        wallet.referral_earned_balance = Decimal("0.00")
        # Preserve current_balance and set cumulative_total to match it
        wallet.cumulative_total = wallet.current_balance
        wallet.balance_source = 'recharge'
        wallet.is_fake_display_mode = False
        wallet.completed_withdrawals = (wallet.completed_withdrawals or 0) + 1
        wallet.info_alert_day = True
        wallet.save(update_fields=[
            "cumulative_total",
            "product_commission",
            "referral_commission",
            "referral_earned_balance",
            "balance_source",
            "is_fake_display_mode",
            "completed_withdrawals",
            "info_alert_day",
        ])

        # Reset task queue for the new cycle so fresh assignments follow the current daily limit
        UserProductTask.objects.filter(user=withdrawal.user).delete()

        # Remove all admin-configured user cycle state so the next cycle starts clean
        reset_user_cycle_state(withdrawal.user)

        # Reset referrer's referral commission rate (if any) to keep parity with other resets
        referrer = getattr(withdrawal.user, "referred_by", None)
        if referrer:
            referrer_setting, _ = CommissionSetting.objects.get_or_create(user=referrer)
            if referrer_setting.referral_rate != Decimal("0.00"):
                referrer_setting.referral_rate = Decimal("0.00")
                referrer_setting.save(update_fields=["referral_rate"])

        # Optional extra data from POST (hash / notes)
        transaction_hash = ""
        admin_notes = withdrawal.admin_notes or ""
        if request.method == "POST":
            transaction_hash = request.POST.get("transaction_hash", "").strip()
            admin_notes = request.POST.get("admin_notes", admin_notes).strip()

        # Update withdrawal record
        withdrawal.status = "APPROVED"
        if transaction_hash:
            withdrawal.transaction_hash = transaction_hash
        if admin_notes:
            withdrawal.admin_notes = admin_notes
        withdrawal.processed_by = request.user
        withdrawal.processed_at = timezone.now()
        withdrawal.save()

        messages.success(
            request,
            f"Withdrawal of ${withdrawal.amount} for {withdrawal.user.username} approved and balance deducted."
        )

    notify_roles(
        roles=("customerservice",),
        title="Withdrawal approved",
        message=f"{withdrawal.user.username}'s withdrawal of ${withdrawal.amount} was approved.",
        category="withdraw_approved",
        metadata={
            "username": withdrawal.user.username,
            "amount": str(withdrawal.amount),
            "network": withdrawal.network,
            "wallet_address": withdrawal.wallet_address,
            "event": "withdraw_request",
            "status": "approved",
            "withdrawal_id": withdrawal.id,
        }
    )

    return redirect("accounts:admin_dashboard")


@login_required
@user_passes_test(lambda u: u.is_authenticated and u.role in ['admin', 'superadmin'])
def reject_withdrawal(request, withdrawal_id):
    """Reject a withdrawal request without changing user wallet balance"""
    withdrawal = get_object_or_404(
        UserWithdrawal, 
        id=withdrawal_id, 
        status__in=["PENDING", "PROCESSING"]
    )
    
    if request.method == "POST":
        admin_notes = request.POST.get("admin_notes", "No reason provided").strip()
        
        # Refund the amount to user's balance
        withdrawal.status = "REJECTED"
        withdrawal.admin_notes = admin_notes
        withdrawal.processed_by = request.user
        withdrawal.processed_at = timezone.now()
        withdrawal.save()
        
        messages.success(
            request, 
            f"Withdrawal of ${withdrawal.amount} for {withdrawal.user.username} rejected."
        )
    else:
        # Quick reject
        admin_notes = "Rejected by admin"
        withdrawal.status = "REJECTED"
        withdrawal.admin_notes = admin_notes
        withdrawal.processed_by = request.user
        withdrawal.processed_at = timezone.now()
        withdrawal.save()
        
        messages.success(
            request, 
            f"Withdrawal of ${withdrawal.amount} rejected."
        )
    
    notify_roles(
        roles=("customerservice",),
        title="Withdrawal rejected",
        message=f"{withdrawal.user.username}'s withdrawal of ${withdrawal.amount} was rejected.",
        category="withdraw_request",
        metadata={
            "username": withdrawal.user.username,
            "amount": str(withdrawal.amount),
            "network": withdrawal.network,
            "wallet_address": withdrawal.wallet_address,
            "event": "withdraw_request",
            "status": "rejected",
            "withdrawal_id": withdrawal.id,
            "admin_notes": admin_notes,
        }
    )
    
    return redirect("accounts:admin_dashboard")


@login_required
@user_passes_test(lambda u: u.is_superuser)
def set_processing(request, withdrawal_id):
    """Mark withdrawal as processing"""
    withdrawal = get_object_or_404(UserWithdrawal, id=withdrawal_id, status="PENDING")
    withdrawal.status = "PROCESSING"
    withdrawal.save()
    messages.info(request, f"Withdrawal marked as processing.")
    return redirect("accounts:admin_dashboard")



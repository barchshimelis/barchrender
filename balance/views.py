# balance/views.py
from decimal import Decimal
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.http import JsonResponse

from balance.models import Wallet, RechargeRequest, RechargeHistory, Voucher, BalanceRequest
from balance.utils import (
    get_wallet_balance,
    create_recharge_request,
    update_wallet_balance,
    upload_voucher,
    approve_recharge,
    reject_recharge,
)
from accounts.models import SuperAdminWallet
from commission.models import Commission

# -----------------------------
# Admin check
# -----------------------------
def is_admin(user):
    return user.is_authenticated and user.role in ["admin", "superadmin"]

# -----------------------------
# Wallet Dashboard
# -----------------------------
# -----------------------------
# Wallet Dashboard
# -----------------------------
@login_required
def wallet_dashboard(request):
    from django.db.models import Sum
    from django.utils import timezone
    from commission.models import Commission
    from decimal import Decimal

    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    pending_recharge = RechargeRequest.objects.filter(user=request.user, status="pending").first()
    history = RechargeHistory.objects.filter(user=request.user).order_by("-action_date")

    # -----------------------------
    # Today's Commissions
    # -----------------------------
    today = timezone.now().date()

    # Today's product commission
    today_product_commission = Commission.objects.filter(
        user=request.user,
        commission_type='self',
        created_at__date=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Today's referral commission
    today_referral_commission = Commission.objects.filter(
        user=request.user,
        commission_type='referral',
        created_at__date=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Combined
    today_commission = today_product_commission + today_referral_commission

    # -----------------------------
    # Context
    # -----------------------------
    superadmin_wallet = SuperAdminWallet.objects.first()
    user_wallet_address = getattr(request.user, "userwalletaddress", None)

    context = {
        "wallet": wallet,  # full wallet object
        "recharge_amounts": [500, 1000, 1500, 2000, 3000, 4000, 5000, 10000],
        "pending_recharge": pending_recharge,
        "history": history,
        "today_product_commission": today_product_commission,
        "today_referral_commission": today_referral_commission,
        "today_commission": today_commission,
        "referral_earned_balance": wallet.referral_earned_balance,
        "is_fake_display_mode": wallet.is_fake_display_mode,
        "balance_source": wallet.balance_source,  # New: Track balance source
        "has_recharged": wallet.has_recharged,    # New: Track recharge status
        "superadmin_wallet": superadmin_wallet,
        "wallet_address": getattr(user_wallet_address, "address", ""),
        "wallet_network": getattr(user_wallet_address, "network", ""),
    }
    return render(request, "balance/wallet_dashboard.html", context)




# -----------------------------
# Recharge Amount Submission (with voucher)
# -----------------------------
@login_required
def recharge_amount(request):
    if request.method == "POST":
        amount = request.POST.get("amount")
        if not amount:
            messages.error(request, _("No amount specified."))
            return redirect("balance:wallet_dashboard")
        try:
            amount = Decimal(amount)
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, _("Invalid amount."))
            return redirect("balance:wallet_dashboard")

        recharge = create_recharge_request(request.user, amount)
        messages.info(request, _("Amount received. Please upload your voucher to complete the request."))
        return redirect("balance:upload_voucher", recharge_id=recharge.id)
    return redirect("balance:wallet_dashboard")


# -----------------------------
# Upload Voucher
# -----------------------------
@login_required
def upload_voucher_view(request, recharge_id):
    recharge_request = get_object_or_404(RechargeRequest, id=recharge_id, user=request.user)
    voucher = Voucher.objects.filter(recharge_request=recharge_request).first()

    if request.method == "POST" and request.FILES.get("voucher_file"):
        file = request.FILES["voucher_file"]
        upload_voucher(recharge_request, file)
        messages.success(request, _("Voucher uploaded successfully. Await admin approval."))
        return redirect("balance:upload_voucher", recharge_id=recharge_request.id)

    superadmin_wallet = SuperAdminWallet.objects.first()
    context = {
        "recharge_request": recharge_request,
        "voucher": voucher,
        "superadmin_wallet": superadmin_wallet,
    }
    return render(request, "balance/upload_voucher.html", context)


# -----------------------------
# Approve Voucher (Admin)
# -----------------------------
@login_required
@user_passes_test(is_admin)
def approve_voucher(request, voucher_id):
    voucher = get_object_or_404(Voucher, id=voucher_id)
    recharge_request = voucher.recharge_request
    user = recharge_request.user

    if request.method == "POST":
        voucher_file = voucher.file if voucher.file else None
        approve_recharge(recharge_request, voucher_file)

        # Delete voucher file safely
        if voucher.file and os.path.isfile(voucher.file.path):
            os.remove(voucher.file.path)
        voucher.delete()

        wallet = Wallet.objects.get(user=user)
        messages.success(request, _("Voucher for %(user)s approved. Current balance: %(amount)s") % {
            "user": user.username,
            "amount": wallet.current_balance,
        })

    return redirect("accounts:admin_dashboard")


# -----------------------------
# Reject Voucher (Admin)
# -----------------------------
@login_required
@user_passes_test(is_admin)
def reject_voucher(request, voucher_id):
    voucher = get_object_or_404(Voucher, id=voucher_id)
    recharge_request = voucher.recharge_request
    user = recharge_request.user

    if request.method == "POST":
        voucher_file = voucher.file if voucher.file else None
        reject_recharge(recharge_request, voucher_file)

        if voucher.file and os.path.isfile(voucher.file.path):
            os.remove(voucher.file.path)
        voucher.delete()

        messages.info(request, _("Voucher for %(user)s has been rejected.") % {"user": user.username})

    return redirect("accounts:admin_dashboard")


# -----------------------------
# Reject Recharge (Admin - no voucher)
# -----------------------------
@login_required
@user_passes_test(is_admin)
def reject_recharge_request(request, recharge_id):
    recharge_request = get_object_or_404(RechargeRequest, id=recharge_id)

    if request.method == "POST":
        voucher = getattr(recharge_request, "voucher", None)
        voucher_file = voucher.file if voucher and voucher.file else None
        reject_recharge(recharge_request, voucher_file)

        if voucher:
            if voucher_file and os.path.isfile(voucher_file.path):
                os.remove(voucher_file.path)
            voucher.delete()

        messages.info(request, _("Recharge request for %(user)s has been removed.") % {
            "user": recharge_request.user.username
        })

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"status": "ok"})

    return redirect("accounts:admin_dashboard")


# -----------------------------
# Update Recharge Amount (Admin)
# -----------------------------
@login_required
@user_passes_test(is_admin)
def update_recharge_amount(request, recharge_id):
    recharge = get_object_or_404(RechargeRequest, id=recharge_id)
    if request.method == "POST":
        amount = request.POST.get("amount")
        if amount:
            try:
                recharge.amount = Decimal(amount)
                recharge.save()
                messages.success(request, _("Recharge amount updated to %(amount)s") % {
                    "amount": recharge.amount
                })
            except:
                messages.error(request, _("Invalid amount"))
    return redirect("accounts:admin_dashboard")


# ----------------------------
# Request Balance
# ----------------------------
@login_required
def request_balance_view(request):
    if request.method == "POST":
        amount = request.POST.get("amount")
        if not amount:
            messages.error(request, _("No amount specified."))
            return redirect("balance:wallet_dashboard")
        try:
            amount = Decimal(amount)
            if amount <= 0:
                messages.error(request, _("Amount must be positive."))
                return redirect("balance:wallet_dashboard")
        except:
            messages.error(request, _("Invalid amount."))
            return redirect("balance:wallet_dashboard")

        # Create a balance request
        BalanceRequest.objects.create(user=request.user, amount=amount)
        messages.success(request, _("Your balance request has been submitted."))
        return redirect("balance:wallet_dashboard")
    return redirect("balance:wallet_dashboard")


# -----------------------------
# Approve Balance Request (Admin)
# -----------------------------
@login_required
@user_passes_test(is_admin)
def approve_balance_request(request, request_id):
    balance_request = get_object_or_404(BalanceRequest, id=request_id)
    if request.method == "POST":
        wallet = Wallet.objects.get(user=balance_request.user)
        wallet.add_recharge(balance_request.amount)
        balance_request.status = "approved"
        balance_request.processed_at = timezone.now()
        balance_request.save()
        messages.success(request, _("Balance request for %(user)s approved.") % {
            "user": balance_request.user.username
        })
    return redirect("accounts:admin_dashboard")


# -----------------------------
# Get Wallet Balance API (Real-time)
# -----------------------------
@login_required
def get_wallet_balance_api(request):
    """API endpoint to get wallet balance data in JSON for real-time updates"""
    from django.http import JsonResponse
    
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    today = timezone.now().date()
    
    # Today's commissions
    today_product_commission = Commission.objects.filter(
        user=request.user,
        commission_type='self',
        created_at__date=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    today_referral_commission = Commission.objects.filter(
        user=request.user,
        commission_type='referral',
        created_at__date=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    data = {
        'current_balance': float(wallet.current_balance),
        'product_commission': float(wallet.product_commission),
        'referral_commission': float(wallet.referral_commission),
        'today_product_commission': float(today_product_commission),
        'today_referral_commission': float(today_referral_commission),
        'today_commission': float(today_product_commission + today_referral_commission),
        'referral_earned_balance': float(wallet.referral_earned_balance),
        'is_fake_display_mode': wallet.is_fake_display_mode,
    }
    return JsonResponse(data)
   
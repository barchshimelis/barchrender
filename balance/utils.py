import os
from decimal import Decimal
from django.core.files.base import File
from django.db import transaction
from django.utils import timezone
from balance.models import Wallet, RechargeRequest, Voucher, RechargeHistory
from stoppoints.models import StopPoint, StopPointProgress
from stoppoints.utils import get_active_stop_point, apply_recharge_to_stop_point
from products.models import UserProductTask
 
from notification.utils import notify_roles, create_admin_dashboard_event



# -----------------------------
# Wallet Utilities
# -----------------------------
def get_wallet(user):
    """Get or create wallet for a user."""
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet

def get_wallet_balance(user):
    """
    Returns total dynamic balance: current + product + referral
    """
    wallet = get_wallet(user)
    return wallet.current_balance


def handle_stop_point_recharge(user, wallet, recharge_amount):
    """Apply a recharge toward the active stop point requirement and credit bonus when cleared."""
    stop_point = get_active_stop_point(user)
    if not stop_point:
        return None

    if recharge_amount is None:
        return stop_point.required_balance_remaining or Decimal("0.00")

    new_remaining = apply_recharge_to_stop_point(stop_point, recharge_amount)
    if new_remaining is None:
        return None

    if new_remaining <= Decimal("0.00"):
        finalize_stop_point_clearance(user, wallet, stop_point)

    return new_remaining


def finalize_stop_point_clearance(user, wallet, stop_point):
    """Mark stop point as cleared and disburse any pending bonus."""
    # Credit only the bonus to wallet balance (required balance stays as pricing pool)
    bonus_amount = Decimal(stop_point.special_bonus_amount or Decimal("0.00"))
    if bonus_amount > Decimal("0.00"):
        wallet.current_balance += bonus_amount
        wallet.save(update_fields=["current_balance"])

    # Bonus is reflected in current balance only; product commission tracks task prices.
    if bonus_amount > Decimal("0.00"):
        stop_point.bonus_disbursed = True
        stop_point.bonus_disbursed_at = timezone.now()

    updates = []
    if bonus_amount > Decimal("0.00"):
        updates.extend(["bonus_disbursed", "bonus_disbursed_at"])
    if stop_point.required_balance_remaining not in (None, Decimal("0.00")):
        stop_point.required_balance_remaining = Decimal("0.00")
        updates.append("required_balance_remaining")

    if stop_point.status != "approved":
        stop_point.status = "approved"
        updates.append("status")

    if updates:
        stop_point.save(update_fields=updates)

    progress, _ = StopPointProgress.objects.get_or_create(user=user)
    progress.last_cleared = stop_point
    progress.is_stopped = False
    progress.save(update_fields=["last_cleared", "is_stopped"])

@transaction.atomic
def update_wallet_balance(user, amount, action="add", balance_type="current"):
    """
    Generic wallet update.
    balance_type: 'current', 'product_commission', 'referral_commission'
    action: 'add' or 'subtract'
    """
    wallet = get_wallet(user)
    amount = Decimal(amount)

    updated_fields = set()

    if balance_type == "current":
        if action == "add":
            wallet.current_balance += amount
            updated_fields.add("current_balance")
        elif action == "subtract":
            if wallet.current_balance >= amount:
                wallet.current_balance -= amount
                updated_fields.add("current_balance")
            else:
                return False
    elif balance_type == "product_commission":
        if action == "add":
            wallet.product_commission += amount
            updated_fields.add("product_commission")
        elif action == "subtract":
            if wallet.product_commission >= amount:
                wallet.product_commission -= amount
                updated_fields.add("product_commission")
            else:
                return False
    elif balance_type == "referral_commission":
        if action == "add":
            wallet.referral_commission += amount
            updated_fields.add("referral_commission")
        elif action == "subtract":
            if wallet.referral_commission >= amount:
                wallet.referral_commission -= amount
                updated_fields.add("referral_commission")
            else:
                return False
    else:
        return False

    wallet.save(update_fields=list(updated_fields))
    return wallet

# -----------------------------
# Recharge Utilities
# -----------------------------
@transaction.atomic
def create_recharge_request(user, amount):
    """
    Create a pending recharge request
    """
    amount = Decimal(amount)
    recharge = RechargeRequest.objects.create(user=user, amount=amount)

    notify_roles(
        roles=("customerservice",),
        title="New recharge request",
        message=f"{user.username} requested a recharge of ${amount}.",
        category="recharge_request",
        metadata={
            "username": user.username,
            "amount": str(amount),
            "referrer": getattr(user.referred_by, "username", ""),
            "event": "recharge_request",
            "status": "pending",
            "recharge_id": recharge.id,
        },
    )

    create_admin_dashboard_event(
        user=user,
        event_type="recharge_request",
        message=f"{user.username} requested a recharge of ${amount}.",
        metadata={
            "amount": str(amount),
            "event": "recharge_request",
            "status": "pending",
        },
    )

    return recharge

@transaction.atomic
def approve_recharge(recharge_request, voucher_file=None):
    """
    Approve recharge request:
    - update wallet current_balance
    - set balance_source to 'recharge'
    - set has_recharged to True
    - disable fake mode
    - mark recharge approved
    - log history
    - clear stop point if balance is now sufficient
    """
    if recharge_request.status != "pending":
        raise ValueError("Recharge already processed")

    user = recharge_request.user
    wallet = Wallet.objects.select_for_update().get(user=user)

    # 1. Update wallet with new balance source tracking
    wallet.current_balance += recharge_request.amount
    wallet.balance_source = 'recharge'
    wallet.has_recharged = True
    wallet.is_fake_display_mode = False  # Exit fake mode
    wallet.save(update_fields=[
        'current_balance',
        'balance_source',
        'has_recharged',
        'is_fake_display_mode'
    ])

    handle_stop_point_recharge(user, wallet, recharge_request.amount)

    notify_roles(
        roles=("customerservice",),
        title="Recharge approved",
        message=f"{user.username}'s recharge of ${recharge_request.amount} was approved.",
        category="recharge_request",
        metadata={
            "username": user.username,
            "amount": str(recharge_request.amount),
            "referrer": getattr(user.referred_by, "username", ""),
            "event": "recharge_request",
            "status": "approved",
            "recharge_id": recharge_request.id,
        },
    )

    # 2. Mark recharge as approved
    recharge_request.status = "approved"
    recharge_request.save(update_fields=['status'])

    # 3. Log history
    history = RechargeHistory.objects.create(
        user=user,
        recharge_request=recharge_request,
        amount=recharge_request.amount,
        status="approved"
    )
    if voucher_file:
        voucher_file.open('rb')
        history.voucher_file.save(
            os.path.basename(voucher_file.name),
            File(voucher_file),
            save=True
        )
        voucher_file.close()

    return recharge_request

@transaction.atomic
def reject_recharge(recharge_request, voucher_file=None):
    """
    Reject recharge request:
    - mark rejected
    - log history
    """
    if recharge_request.status != "pending":
        raise ValueError("Recharge already processed")

    recharge_request.status = "rejected"
    recharge_request.save()

    history = RechargeHistory.objects.create(
        user=recharge_request.user,
        recharge_request=recharge_request,
        amount=recharge_request.amount,
        status="rejected"
    )
    if voucher_file:
        voucher_file.open('rb')
        history.voucher_file.save(
            os.path.basename(voucher_file.name),
            File(voucher_file),
            save=True
        )
        voucher_file.close()
    return recharge_request

# -----------------------------
# Voucher Utilities
# -----------------------------
@transaction.atomic
def upload_voucher(recharge_request, file):
    """
    Upload or update voucher for recharge
    """
    voucher, _ = Voucher.objects.get_or_create(recharge_request=recharge_request)
    voucher.file = file
    voucher.save()
    return voucher

# -----------------------------
# History Utilities
# -----------------------------
def get_recharge_history_maps(user_ids):
    """Return history entries and document-ready histories for the given user IDs."""
    histories = (
        RechargeHistory.objects.filter(user_id__in=user_ids)
        .select_related('recharge_request', 'recharge_request__voucher')
        .order_by('-action_date')
    )

    history_map = {}
    history_documents_map = {}

    for history in histories:
        history_map.setdefault(history.user_id, []).append(history)

        voucher_url = None
        if history.voucher_file:
            voucher_url = getattr(history.voucher_file, 'url', None)
        else:
            recharge_request = history.recharge_request
            voucher = getattr(recharge_request, 'voucher', None) if recharge_request else None
            if voucher and getattr(voucher, 'file', None):
                voucher_url = getattr(voucher.file, 'url', None)

        if voucher_url:
            history.display_voucher_url = voucher_url
            history_documents_map.setdefault(history.user_id, []).append(history)

    return history_map, history_documents_map

# -----------------------------
# Fake Display Mode Utilities
# -----------------------------
@transaction.atomic
def activate_fake_display_mode(user, referral_amount):
    """
    Activates fake display mode when user receives referral earnings.
    Only activates if user has no current_balance (pure referral earnings).
    """
    from django.utils import timezone
    wallet, _ = Wallet.objects.get_or_create(user=user)
    
    # Only activate fake mode if user has no recharged balance
    if wallet.current_balance == 0 and not wallet.is_fake_display_mode:
        wallet.referral_earned_balance += referral_amount
        wallet.is_fake_display_mode = True
        wallet.fake_mode_started_at = timezone.now()
        wallet.save(update_fields=['referral_earned_balance', 'is_fake_display_mode', 'fake_mode_started_at'])
        return True
    return False

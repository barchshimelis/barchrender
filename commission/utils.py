from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from balance.models import Wallet
from commission.models import Commission, CommissionSetting
from products.models import UserProductTask
from django.contrib.auth import get_user_model

User = get_user_model()

# -----------------------------
# Helper: Get or Create Commission Record
# -----------------------------
def get_or_create_commission(user, product_name, amount, commission_type, triggered_by):
    """
    Idempotent: get existing commission record or create new one.
    """
    commission, created = Commission.objects.get_or_create(
        user=user,
        product_name=product_name,
        commission_type=commission_type,
        triggered_by=triggered_by,
        defaults={'amount': amount}
    )
    return commission, created

# -----------------------------
# Get Commission Rates
# -----------------------------
def get_commission_rates(user):
    """
    Fetch latest commission rates for a user.
    """
    setting = CommissionSetting.objects.filter(user=user).order_by("-updated_at").first()
    return {
        "product_rate": Decimal(setting.product_rate) if setting else Decimal("0.00"),
        "referral_rate": Decimal(setting.referral_rate) if setting else Decimal("0.00"),
    }

# -----------------------------
# Process Product Completion
# -----------------------------
@transaction.atomic
def process_product_completion(user, product_task):
    """
    Handles product completion:
    - Credit product price (or real price in fake mode) to current_balance
    - Add product commission to user (idempotent) and make it spendable immediately
    - Add referral commission to referrer (idempotent)
    """
    wallet, _ = Wallet.objects.get_or_create(user=user)

    print(f"[DEBUG] Processing task completion - Task ID: {product_task.id}")
    print(f"[DEBUG] Wallet balance source: {wallet.balance_source}")
    print(f"[DEBUG] Task price: {product_task.price}, Real price: {getattr(product_task, 'real_price', 'N/A')}")
    print(f"[DEBUG] Current balance before credit: {wallet.current_balance}")

    # Determine which price to use for credit and commission calculation
    if wallet.balance_source == 'referral' or getattr(product_task, 'is_fake_mode_task', False):
        credit_amount = getattr(product_task, 'real_price', product_task.price)
    else:
        credit_amount = product_task.price

    commission_base = credit_amount

    if not credit_amount or Decimal(credit_amount) <= 0:
        return {"warning": "Task has no price and cannot be completed."}

    credit_amount = Decimal(credit_amount).quantize(Decimal("0.01"))
    commission_base = Decimal(commission_base).quantize(Decimal("0.01"))

    wallet.current_balance += credit_amount
    wallet_updated_fields = {"current_balance"}

    rates = get_commission_rates(user)
    product_commission_amount = commission_base
    product_rate = Decimal(rates.get("product_rate", Decimal("0.00")))
    if product_rate and product_rate > Decimal("0.00"):
        base_amount = (commission_base * Decimal("100.00") / product_rate).quantize(Decimal("0.01"))
    else:
        base_amount = Decimal("0.00")

    # Use task-specific identifier so each completed task grants its own commission
    product_identifier = f"Task {product_task.id} - Product {product_task.product.id}"

    # Record product commission idempotently (duplicate protection per task)
    product_commission_obj, product_created = get_or_create_commission(
        user=user,
        product_name=product_identifier,
        amount=product_commission_amount,
        commission_type="self",
        triggered_by=user
    )

    if product_created:
        wallet.product_commission += product_commission_amount
        wallet_updated_fields.update({"product_commission"})
    else:
        product_commission_amount = product_commission_obj.amount

    # Referral commission - calculated on REAL amount
    referral_amount = Decimal("0.00")
    referrer = getattr(user, "referred_by", None)
    if referrer:
        # Get REFERRER's commission rates (not referee's)
        referrer_rates = get_commission_rates(referrer)
        referral_amount = (base_amount * referrer_rates["referral_rate"] / Decimal("100.00")).quantize(Decimal("0.01"))

        ref_commission_obj, ref_created = get_or_create_commission(
            user=referrer,
            product_name=product_identifier,
            amount=referral_amount,
            commission_type='referral',
            triggered_by=user
        )

        if ref_created:
            ref_wallet, _ = Wallet.objects.get_or_create(user=referrer)
            ref_wallet.current_balance += referral_amount
            ref_wallet.referral_earned_balance += referral_amount
            ref_wallet.referral_commission += referral_amount
            ref_update_fields = ["current_balance", "referral_earned_balance", "referral_commission"]
            
            if not ref_wallet.has_recharged:
                ref_wallet.balance_source = 'referral'
                ref_update_fields.append("balance_source")
            
            ref_wallet.save(update_fields=ref_update_fields)
        else:
            referral_amount = ref_commission_obj.amount

    wallet.save(update_fields=list(wallet_updated_fields))

    # Mark the task as completed
    product_task.is_completed = True
    product_task.completed_at = timezone.now()
    product_task.save()

    # Check if all daily tasks are completed
    from products.utils import get_daily_task_limit
    daily_limit = get_daily_task_limit(user)
    completed_tasks_count = UserProductTask.objects.filter(
        user=user,
        is_completed=True
    ).count()

    if daily_limit and completed_tasks_count >= daily_limit:
        referrer = getattr(user, "referred_by", None)
        if referrer:
            referrer_setting, _ = CommissionSetting.objects.get_or_create(user=referrer)
            if referrer_setting.referral_rate != Decimal("0.00"):
                referrer_setting.referral_rate = Decimal("0.00")
                referrer_setting.save(update_fields=["referral_rate"])
    
    # Commissions stay in their separate fields - no consolidation needed

    return {
        "product_commission": product_commission_amount,
        "referral_commission": referral_amount,
        "warning": None
    }

# -----------------------------
# Calculate Product Commission (without wallet update)
# -----------------------------
@transaction.atomic
def calculate_product_commission(user, product):
    rates = get_commission_rates(user)
    rate = rates["product_rate"]
    if rate <= 0:
        return None

    amount = (Decimal(product.price) * rate / Decimal('100.00')).quantize(Decimal('0.01'))

    commission = Commission.objects.create(
        user=user,
        product_name=getattr(product, 'file', f'Product {product.id}'),
        amount=amount,
        commission_type='self',
    )
    return commission

# -----------------------------
# Add Referral Commission (idempotent)
# -----------------------------
@transaction.atomic
def add_referral_commission_atomic(referrer, referred_user, product):
    if not referrer or referrer.role != 'user' or referred_user.role != 'user':
        return Decimal('0.00')

    rates = get_commission_rates(referrer)
    referral_rate = rates["referral_rate"]
    if referral_rate <= 0:
        return Decimal('0.00')

    product_name = getattr(product, 'file', f'Product {product.id}')

    # Idempotency: check existing record
    existing = Commission.objects.filter(
        user=referrer,
        product_name=product_name,
        commission_type='referral',
        triggered_by=referred_user
    ).first()

    if existing:
        return existing.amount

    referral_amount = (Decimal(product.price) * referral_rate / Decimal('100.00')).quantize(Decimal('0.01'))

    wallet, _ = Wallet.objects.get_or_create(user=referrer)
    # Add to SPENDABLE balance (current_balance) in real-time
    wallet.current_balance += referral_amount
    wallet.referral_commission += referral_amount
    wallet.save(update_fields=['current_balance', 'referral_commission'])

    Commission.objects.create(
        user=referrer,
        product_name=product_name,
        commission_type='referral',
        amount=referral_amount,
        triggered_by=referred_user
    )

    return referral_amount

# -----------------------------
# Get Total Commission
# -----------------------------
def get_total_commission(user):
    total = Commission.objects.filter(user=user).aggregate(total=Sum('amount'))['total']
    return total if total else Decimal('0.00')


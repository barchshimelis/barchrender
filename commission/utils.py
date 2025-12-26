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
    - Deduct product price from wallet (fake mode uses real_price, real mode uses price)
    - Add product commission to user (idempotent)
    - Add referral commission to referrer (idempotent)
    - Save wallet totals
    """
    wallet, _ = Wallet.objects.get_or_create(user=user)

    # Debug information
    print(f"[DEBUG] Processing task completion - Task ID: {product_task.id}")
    print(f"[DEBUG] Wallet balance source: {wallet.balance_source}")
    print(f"[DEBUG] Task price: {product_task.price}, Real price: {getattr(product_task, 'real_price', 'N/A')}")
    print(f"[DEBUG] Current balance: {wallet.current_balance}, Referral balance: {wallet.referral_earned_balance}")
    
    # Determine which price to use for deduction and commission calculation based on wallet's balance_source
    if wallet.balance_source == 'referral' or (hasattr(product_task, 'is_fake_mode_task') and product_task.is_fake_mode_task):
        # In referral mode, use real_price if available, otherwise fall back to price
        actual_deduction = getattr(product_task, 'real_price', product_task.price)
        commission_base = actual_deduction
        balance_source = 'referral_earned_balance'
        
        # Ensure we have enough referral balance
        if wallet.referral_earned_balance < actual_deduction:
            print(f"[DEBUG] Insufficient referral balance: {wallet.referral_earned_balance} < {actual_deduction}")
            # If no referral balance but have main balance, switch to main balance
            if wallet.current_balance >= actual_deduction:
                print("[DEBUG] Switching to main balance")
                wallet.balance_source = 'recharge'
                wallet.is_fake_display_mode = False
                wallet.save(update_fields=['balance_source', 'is_fake_display_mode'])
                balance_source = 'current_balance'
            else:
                return {"warning": f"Insufficient balance (${wallet.referral_earned_balance:.2f}) for this task (${actual_deduction:.2f} required)"}
    else:
        # In recharge mode, use regular price
        actual_deduction = product_task.price
        commission_base = product_task.price
        balance_source = 'current_balance'
        
        # Ensure we have enough current balance
        if wallet.current_balance < actual_deduction:
            # If no current balance but have referral balance, switch to referral
            if wallet.referral_earned_balance >= actual_deduction:
                print("[DEBUG] Switching to referral balance")
                wallet.balance_source = 'referral'
                wallet.is_fake_display_mode = True
                wallet.save(update_fields=['balance_source', 'is_fake_display_mode'])
                balance_source = 'referral_earned_balance'
            else:
                return {"warning": f"Insufficient balance (${wallet.current_balance:.2f}) for this task (${actual_deduction:.2f} required)"}

    # Check if price is valid
    if not actual_deduction or actual_deduction <= 0:
        return {"warning": "Task has no price and cannot be completed."}

    # Deduct from the appropriate balance source
    if balance_source == 'referral_earned_balance':
        print(f"[DEBUG] Deducting ${actual_deduction} from current_balance (using referral mode)")
        # Only deduct from current_balance (spendable)
        # referral_earned_balance stays as a fixed tracker (never decreases)
        wallet.current_balance -= actual_deduction

        print(f"[DEBUG] After deduction - Current: ${wallet.current_balance}, Referral Earned (tracker): ${wallet.referral_earned_balance}")

        update_fields = {'current_balance'}
        if wallet.current_balance <= 0:
            wallet.balance_source = 'recharge'
            wallet.is_fake_display_mode = False
            print(f"[DEBUG] Current balance depleted, switching to recharge mode")
            update_fields.update({'balance_source', 'is_fake_display_mode'})

        if wallet.current_balance < Decimal("0.02"):
            from products.utils import get_small_leftover_amount
            wallet.current_balance = get_small_leftover_amount()
            print(f"[DEBUG] Applied small leftover buffer: ${wallet.current_balance}")
            update_fields.add('current_balance')

        wallet.save(update_fields=list(update_fields))
    else:
        print(f"[DEBUG] Deducting ${actual_deduction} from main balance")
        wallet.current_balance -= actual_deduction
        update_fields = {'current_balance'}
        # If we've run out of main balance but have referral balance, switch to referral
        if wallet.current_balance <= 0 and wallet.referral_earned_balance > 0:
            wallet.balance_source = 'referral'
            wallet.is_fake_display_mode = True
            update_fields.update({'balance_source', 'is_fake_display_mode'})

        if wallet.current_balance < Decimal("0.02"):
            from products.utils import get_small_leftover_amount
            wallet.current_balance = get_small_leftover_amount()
            print(f"[DEBUG] Applied small leftover buffer: ${wallet.current_balance}")
            update_fields.add('current_balance')

        wallet.save(update_fields=list(update_fields))

    # Calculate product commission on REAL amount (not fake display price)
    rates = get_commission_rates(user)
    product_commission_amount = (Decimal(commission_base) * rates["product_rate"] / Decimal("100.00")).quantize(Decimal("0.01"))

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
        wallet.cumulative_total += product_commission_amount
    else:
        product_commission_amount = product_commission_obj.amount

    # Referral commission - calculated on REAL amount
    referral_amount = Decimal("0.00")
    referrer = getattr(user, "referred_by", None)
    if referrer:
        # Get REFERRER's commission rates (not referee's)
        referrer_rates = get_commission_rates(referrer)
        referral_amount = (Decimal(commission_base) * referrer_rates["referral_rate"] / Decimal("100.00")).quantize(Decimal("0.01"))

        ref_commission_obj, ref_created = get_or_create_commission(
            user=referrer,
            product_name=product_identifier,
            amount=referral_amount,
            commission_type='referral',
            triggered_by=user
        )

        if ref_created:
            ref_wallet, _ = Wallet.objects.get_or_create(user=referrer)
            # Add to BOTH balances:
            # 1. current_balance: Makes it spendable
            # 2. referral_earned_balance: Tracks referral earnings for fake mode detection
            ref_wallet.current_balance += referral_amount
            ref_wallet.referral_earned_balance += referral_amount
            ref_wallet.referral_commission += referral_amount
            ref_wallet.cumulative_total += referral_amount
            
            # Set balance_source to 'referral' ONLY if user hasn't recharged
            if not ref_wallet.has_recharged:
                ref_wallet.balance_source = 'referral'
                ref_wallet.save(update_fields=["current_balance", "referral_earned_balance", "referral_commission", "cumulative_total", "balance_source"])
            else:
                ref_wallet.save(update_fields=["current_balance", "referral_earned_balance", "referral_commission", "cumulative_total"])
        else:
            referral_amount = ref_commission_obj.amount

    # Save user's wallet with appropriate fields
    if balance_source == 'referral_earned_balance':
        wallet.save(update_fields=["referral_earned_balance", "product_commission", "cumulative_total"])
    else:
        wallet.save(update_fields=["current_balance", "product_commission", "cumulative_total"])

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
    wallet.cumulative_total += referral_amount
    wallet.save(update_fields=['current_balance', 'referral_commission', 'cumulative_total'])

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


import random
import string
from decimal import Decimal, ROUND_DOWN

from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from accounts.models import CustomUser
from balance.models import Wallet
from commission.utils import process_product_completion
from stoppoints.models import StopPoint
from stoppoints.utils import get_next_pending_stoppoint, get_user_stoppoint_progress

from .models import Product, UserProductTask


SMALL_LEFTOVER_MIN = Decimal("0.02")
SMALL_LEFTOVER_MAX = Decimal("0.05")
STOPPOINT_LEFTOVER_MIN = Decimal("7.00")
STOPPOINT_LEFTOVER_MAX = Decimal("15.00")


def get_stoppoint_leftover_buffer() -> Decimal:
    """Return a dynamic leftover buffer between $7 and $15 for stop points."""
    value = random.uniform(float(STOPPOINT_LEFTOVER_MIN), float(STOPPOINT_LEFTOVER_MAX))
    return Decimal(value).quantize(Decimal("0.01"))


def get_small_leftover_amount() -> Decimal:
    """Return a random leftover buffer between $0.02 and $0.05."""
    value = random.uniform(float(SMALL_LEFTOVER_MIN), float(SMALL_LEFTOVER_MAX))
    return Decimal(value).quantize(Decimal("0.01"))


def format_product_code(raw_code: str) -> str:
    """Return product codes in the 'XJR-AS4-45J' style (LLL-LLD-DDL)."""
    alphabet = string.ascii_uppercase
    digits_set = "0123456789"

    def random_letters(count: int) -> str:
        return ''.join(random.choice(alphabet) for _ in range(count))

    def random_digits(count: int) -> str:
        return ''.join(random.choice(digits_set) for _ in range(count))

    if not raw_code:
        segment_one = random_letters(3)
        segment_two = f"{random_letters(2)}{random_digits(1)}"
        segment_three = f"{random_digits(2)}{random_letters(1)}"
        return f"{segment_one}-{segment_two}-{segment_three}"

    normalized = ''.join(ch for ch in raw_code.upper() if ch.isalnum())
    letters = [ch for ch in normalized if ch.isalpha()]
    digits = [ch for ch in normalized if ch.isdigit()]

    def take_letter() -> str:
        return letters.pop(0) if letters else random.choice(alphabet)

    def take_digit() -> str:
        return digits.pop(0) if digits else random.choice(digits_set)

    segment_one = ''.join(take_letter() for _ in range(3))
    segment_two = ''.join(
        take_letter() if idx < 2 else take_digit()
        for idx in range(3)
    )
    segment_three = ''.join(
        take_digit() if idx < 2 else take_letter()
        for idx in range(3)
    )

    return f"{segment_one}-{segment_two}-{segment_three}"


def get_daily_completed_tasks(user):
    today = timezone.now().date()
    return (
        UserProductTask.objects.filter(user=user, is_completed=True)
        .filter(
            Q(completed_at__date=today)
            | (Q(completed_at__isnull=True) & Q(created_at__date=today))
        )
        .count()
    )


def get_all_products_queryset():
    return Product.objects.filter(is_active=True).order_by('sequence_in_cycle', 'id')


def find_next_product_for_user(user):
    products = list(get_all_products_queryset())
    if not products:
        return None

    # If user already has an active task, present that product again
    existing_task = (
        UserProductTask.objects
        .filter(user=user, is_completed=False)
        .select_related('product')
        .order_by('created_at')
        .first()
    )
    if existing_task and existing_task.product:
        return existing_task.product

    # Avoid giving the user a product they already have assigned but incomplete
    active_product_ids = set(
        UserProductTask.objects.filter(user=user, is_completed=False).values_list('product_id', flat=True)
    )
    available_products = [p for p in products if p.id not in active_product_ids]
    if not available_products:
        available_products = products

    return random.choice(available_products)


def calculate_task_pricing(user, wallet, next_product, next_task_number, daily_limit):
    stop_points = list(StopPoint.objects.filter(user=user).order_by('point'))
    if daily_limit and daily_limit > 0:
        pricing_ceiling = daily_limit
    else:
        highest_stop_point = stop_points[-1].point if stop_points else next_task_number
        pricing_ceiling = max(next_task_number, highest_stop_point)

    stop_points = [sp for sp in stop_points if sp.point <= pricing_ceiling]
    stop_points_lookup = {sp.point: sp for sp in stop_points}
    upcoming_stop_points = [sp for sp in stop_points if sp.point >= next_task_number]

    current_stop_point = upcoming_stop_points[0] if upcoming_stop_points else None

    # --- Stop Point Trigger ---
    slicing_stop_point = current_stop_point
    if current_stop_point and current_stop_point.point == next_task_number:
        required_balance = Decimal(current_stop_point.required_balance or 0)
        task_price_snapshot = getattr(next_product, "price", None)
        if task_price_snapshot is None:
            task_price_snapshot = required_balance
        else:
            task_price_snapshot = Decimal(task_price_snapshot)

        minimum_required_balance = max(required_balance, task_price_snapshot).quantize(Decimal("0.01"))

        if wallet.current_balance < minimum_required_balance:
            remaining_gap = (minimum_required_balance - wallet.current_balance).quantize(Decimal("0.01"))
            if remaining_gap < Decimal("0.00"):
                remaining_gap = Decimal("0.00")
            return next_product, f"Recharge required {remaining_gap}", minimum_required_balance, minimum_required_balance, False
        # Stop point satisfied (user recharged enough); look ahead to the next stop for pricing slice
        slicing_stop_point = upcoming_stop_points[1] if len(upcoming_stop_points) > 1 else None

    # --- Fake Mode Pricing (referral-only balance users) ---
    if wallet.balance_source == 'referral' and not wallet.has_recharged and wallet.referral_earned_balance > 0:
        available_balance = wallet.current_balance
        leftover_buffer = get_small_leftover_amount()
        if available_balance <= leftover_buffer:
            spendable_balance = Decimal("0.00")
        else:
            spendable_balance = (available_balance - leftover_buffer).quantize(Decimal("0.01"))
        if spendable_balance <= Decimal("0.00"):
            return None, "Insufficient referral balance to continue tasks. Please recharge.", None, None, False
        if not wallet.is_fake_display_mode:
            wallet.is_fake_display_mode = True
            wallet.save(update_fields=['is_fake_display_mode'])

        remaining_tasks = pricing_ceiling - (next_task_number - 1)
        real_price = calculate_real_task_price(spendable_balance, remaining_tasks)
        real_price = min(real_price, spendable_balance)
        if real_price <= Decimal("0.00"):
            return None, "Insufficient referral balance to continue tasks. Please recharge.", None, None, False
        fake_price = generate_fake_display_price()
        return next_product, None, fake_price, real_price, True

    # --- Normal Mode Pricing ---
    # Determine slice bounds using the next pending stop point (if any)
    tasks_done = next_task_number - 1
    if slicing_stop_point:
        allowed_task_end = max(slicing_stop_point.point - 1, tasks_done)
    else:
        allowed_task_end = pricing_ceiling

    allowed_task_end = min(allowed_task_end, pricing_ceiling)
    tasks_in_slice = allowed_task_end - tasks_done
    if tasks_in_slice < 1:
        tasks_in_slice = 1

    slice_budget = wallet.current_balance
    if slicing_stop_point and slicing_stop_point.point > tasks_done:
        # Keep a buffer so the user still has funds when they hit the stop point
        stoppoint_buffer = get_stoppoint_leftover_buffer()
        if slice_budget <= stoppoint_buffer:
            slice_budget = Decimal("0.00")
        else:
            slice_budget = (slice_budget - stoppoint_buffer).quantize(Decimal("0.01"))

    # Auto-enable fake mode if necessary
    if wallet.referral_earned_balance > 0 and not wallet.has_recharged:
        available_balance = wallet.current_balance
        leftover_buffer = get_small_leftover_amount()
        if available_balance <= leftover_buffer:
            spendable_balance = Decimal("0.00")
        else:
            spendable_balance = (available_balance - leftover_buffer).quantize(Decimal("0.01"))
        if spendable_balance <= Decimal("0.00"):
            return None, "Insufficient referral balance to continue tasks. Please recharge.", None, None, False
        wallet.is_fake_display_mode = True
        wallet.balance_source = 'referral'
        wallet.save(update_fields=['is_fake_display_mode', 'balance_source'])
        remaining_tasks = pricing_ceiling - tasks_done
        real_price = calculate_real_task_price(spendable_balance, remaining_tasks)
        real_price = min(real_price, spendable_balance)
        if real_price <= Decimal("0.00"):
            return None, "Insufficient referral balance to continue tasks. Please recharge.", None, None, False
        fake_price = generate_fake_display_price()
        return next_product, None, fake_price, real_price, True

    if slice_budget <= Decimal("0.00"):
        return None, "Insufficient balance to continue tasks. Please recharge.", None, None, False

    spendable_balance = slice_budget
    if spendable_balance <= Decimal("0.00"):
        spendable_balance = Decimal("0.01")

    if tasks_in_slice == 1:
        task_price = spendable_balance.quantize(Decimal("0.01"))
    else:
        prices = distribute_value_unevenly(spendable_balance, tasks_in_slice, leftover_buffer=Decimal("0.00"))
        task_price = prices[0] if prices else spendable_balance.quantize(Decimal("0.01"))

    if task_price <= Decimal("0.00"):
        task_price = Decimal("0.01")

    if task_price <= 0 and next_task_number < pricing_ceiling:
        stop_point = get_next_pending_stoppoint(user, next_task_number)
        if stop_point:
            required_balance = stop_point.required_balance
            return next_product, f"Recharge required {required_balance}", required_balance, required_balance, False
        task_price = Decimal("0.01")

    return next_product, None, task_price, task_price, False


# ----------------------------
# Fake Display Mode Helpers
# ----------------------------
def generate_fake_display_price():
    """
    Generates a single attractive fake price for display (cosmetic only)
    Returns realistic-looking price between $30-$120
    """
    return Decimal(random.uniform(30, 120)).quantize(Decimal("0.01"))

def calculate_real_task_price(referral_balance, remaining_tasks):
    """
    Calculate the real price to deduct per task in fake mode
    Distributes referral balance evenly across remaining tasks
    """
    if remaining_tasks <= 0:
        return Decimal("0.01")
    real_price = (referral_balance / remaining_tasks).quantize(Decimal("0.01"))
    return max(real_price, Decimal("0.01"))  # Ensure minimum price

# ----------------------------
# Get Daily Task Limit
# ----------------------------
def get_daily_task_limit(user):
    try:
        setting = getattr(user, 'commission_setting', None)
        if setting and getattr(setting, 'daily_task_limit', None) is not None:
            return int(setting.daily_task_limit)
    except Exception:
        pass
    return 0

# ----------------------------
# Distribute Value Unevenly with leftover buffer
# ----------------------------
def distribute_value_unevenly(total_amount, num_items, leftover_buffer=Decimal("0.00")):
    """
    Distributes a total amount into `num_items` products unevenly, leaving `leftover_buffer` at the end.
    """
    total_amount = Decimal(total_amount).quantize(Decimal("0.01"))
    if total_amount <= leftover_buffer or num_items <= 0:
        return [Decimal("0.00")] * num_items

    usable_amount = total_amount - leftover_buffer
    avg_price = (usable_amount / num_items).quantize(Decimal("0.01"))
    variation = (avg_price * Decimal("0.20")).quantize(Decimal("0.01"))
    prices = []
    remaining = usable_amount

    for i in range(num_items - 1):
        min_price = max(Decimal("0.01"), avg_price - variation)
        max_price = min(remaining - (Decimal("0.01") * (num_items - 1 - i)), avg_price + variation)
        price = Decimal(random.uniform(float(min_price), float(max_price))).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        prices.append(price)
        remaining -= price

    # Last item gets remaining balance
    prices.append(remaining.quantize(Decimal("0.01")))
    random.shuffle(prices)
    return prices

# ----------------------------
# Get Next Product For User
# ----------------------------
def get_next_product_for_user(user):
    tasks_done = UserProductTask.objects.filter(user=user, is_completed=True).count()
    next_task_number = tasks_done + 1
    wallet, _ = Wallet.objects.get_or_create(user=user)

    daily_limit = get_daily_task_limit(user)
    if daily_limit in (None, 0):
        return None, "Admin must set your daily task limit before you can start tasks.", None, None, False
    has_daily_limit = True

    total_products = Product.objects.filter(is_active=True).count()
    if total_products == 0:
        return None, "No products available. Please contact support.", None, None, False

    round_number = tasks_done // total_products if total_products else 0

    if has_daily_limit and next_task_number > daily_limit:
        return None, f"You have reached your daily task limit of {daily_limit}.", None, None, False

    # Get the next available product for this user
    next_product = find_next_product_for_user(user)
    if not next_product:
        return None, "No products available.", None, None, False

    next_product, block_reason, display_price, real_price, is_fake_mode = calculate_task_pricing(
        user,
        wallet,
        next_product,
        next_task_number,
        daily_limit,
    )
    
    if next_product and not block_reason:
        task_defaults = {
            'task_number': next_task_number,
            'round_number': round_number,
            'is_fake_mode_task': is_fake_mode,
            'price': real_price if is_fake_mode else display_price,
            'fake_display_price': display_price if is_fake_mode else None,
            'real_price': real_price,
            'pricing_snapshot_daily_limit': daily_limit,
        }
        task_obj, created = UserProductTask.objects.get_or_create(
            user=user,
            product=next_product,
            is_completed=False,
            defaults=task_defaults,
        )
        if not created:
            updated_fields = []
            for field, value in task_defaults.items():
                if getattr(task_obj, field) != value:
                    setattr(task_obj, field, value)
                    updated_fields.append(field)
            if updated_fields:
                task_obj.save(update_fields=updated_fields)

    return next_product, block_reason, display_price, real_price, is_fake_mode
# ----------------------------
# Complete Product Task
# ----------------------------
def complete_product_task(user, product_task):
    """
    Complete task:
    - Process product completion (commissions, etc.)
    - Mark task as completed
    - Update completion timestamp
    """
    # Process any completion logic (commissions, etc.)
    result = process_product_completion(user, product_task)

    # Mark the task as completed only when processing succeeds
    if not result.get("warning") and not product_task.is_completed:
        product_task.is_completed = True
        product_task.completed_at = timezone.now()
        product_task.save(update_fields=['is_completed', 'completed_at'])

    # Note: We no longer need to mark products as consumed
    # since we track assignments per user through UserProductTask
    
    return result

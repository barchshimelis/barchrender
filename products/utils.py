import random
import string
from decimal import Decimal, ROUND_DOWN

from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from accounts.models import CustomUser
from balance.models import Wallet, RechargeHistory
from commission.utils import process_product_completion
from commission.models import CommissionSetting
from stoppoints.models import StopPoint
from stoppoints.utils import (
    get_next_pending_stoppoint,
    get_user_stoppoint_progress,
    ensure_stop_point_snapshot,
)

from .models import Product, UserProductTask

STOP_POINT_BLOCK_PREFIX = "STOP_POINT"


def _get_product_rate_multiplier(user):
    setting = getattr(user, "commission_setting", None)
    if setting is None:
        setting = CommissionSetting.objects.filter(user=user).only("product_rate").first()
        if setting:
            user.commission_setting = setting

    rate_percent = Decimal(str(getattr(setting, "product_rate", Decimal("0.00")))) if setting else Decimal("0.00")
    multiplier = (rate_percent / Decimal("100.00")) if rate_percent else Decimal("0.00")
    return multiplier


def _convert_base_to_task_price(base_amount, multiplier):
    base_decimal = Decimal(base_amount or Decimal("0.00"))
    price = (base_decimal * multiplier).quantize(Decimal("0.01")) if multiplier else Decimal("0.00")
    if price <= Decimal("0.00"):
        price = Decimal("0.01")
    return price


def _derive_base_from_price(price_amount, multiplier):
    price_decimal = Decimal(price_amount or Decimal("0.00"))
    if multiplier and multiplier > Decimal("0.00"):
        return (price_decimal / multiplier).quantize(Decimal("0.01"))
    return price_decimal


def _get_initial_pool_amount(user, wallet):
    first_recharge = (
        RechargeHistory.objects.filter(user=user, status="approved")
        .order_by("-action_date")
        .first()
    )
    if first_recharge:
        return Decimal(first_recharge.amount).quantize(Decimal("0.01"))
    return Decimal(wallet.current_balance or Decimal("0.00")).quantize(Decimal("0.01"))


def _serialize_decimal_list(values):
    return [format(Decimal(value).quantize(Decimal("0.01")), "f") for value in values]


def _deserialize_decimal_list(values):
    if not values:
        return []
    return [Decimal(str(value)).quantize(Decimal("0.01")) for value in values]


def _clear_active_slice(progress):
    if not progress:
        return
    updates = []
    fields = [
        "active_slice_pool_base",
        "active_slice_start_task",
        "active_slice_end_task",
        "active_slice_stop_point",
        "active_slice_shares",
    ]
    for field in fields:
        current_value = getattr(progress, field, None)
        if current_value not in (None, []):
            setattr(progress, field, None)
            updates.append(field)
    if updates:
        progress.save(update_fields=updates)


def _reset_active_slice_if_stale(progress, next_task_number):
    if not progress:
        return
    start = progress.active_slice_start_task
    end = progress.active_slice_end_task
    if start and next_task_number < start:
        _clear_active_slice(progress)
        return
    if end and next_task_number > end:
        _clear_active_slice(progress)


def _active_slice_matches(progress, next_task_number, stop_point_id):
    if not progress or not progress.active_slice_shares:
        return False

    start_task = progress.active_slice_start_task
    end_task = progress.active_slice_end_task

    if start_task and next_task_number < start_task:
        return False
    if end_task and next_task_number > end_task:
        return False

    current_stop_id = progress.active_slice_stop_point_id or None
    expected_stop_id = stop_point_id if stop_point_id else None
    return current_stop_id == expected_stop_id


def _store_active_slice(progress, start_task, end_task, stop_point, slice_budget, shares):
    if not progress:
        return
    updates = []
    serialized = _serialize_decimal_list(shares)

    if progress.active_slice_start_task != start_task:
        progress.active_slice_start_task = start_task
        updates.append("active_slice_start_task")

    if progress.active_slice_end_task != end_task:
        progress.active_slice_end_task = end_task
        updates.append("active_slice_end_task")

    quantized_budget = Decimal(slice_budget).quantize(Decimal("0.01"))
    if progress.active_slice_pool_base != quantized_budget:
        progress.active_slice_pool_base = quantized_budget
        updates.append("active_slice_pool_base")

    if (progress.active_slice_stop_point_id or None) != (stop_point.id if stop_point else None):
        progress.active_slice_stop_point = stop_point
        updates.append("active_slice_stop_point")

    progress.active_slice_shares = serialized
    updates.append("active_slice_shares")

    if updates:
        progress.save(update_fields=updates)


def _get_slice_share(progress, next_task_number):
    if not progress or not progress.active_slice_shares:
        return None
    start_task = progress.active_slice_start_task
    end_task = progress.active_slice_end_task
    if not start_task:
        return None
    if end_task and next_task_number > end_task:
        _clear_active_slice(progress)
        return None
    index = next_task_number - start_task
    if index < 0:
        return None
    shares = _deserialize_decimal_list(progress.active_slice_shares)
    if index >= len(shares):
        _clear_active_slice(progress)
        return None
    return shares[index]


def _consume_stop_point_slice(progress, stop_point, slice_budget, slice_start_task, slice_end_task, next_task_number):
    stop_point_id = stop_point.id if stop_point else None

    if _active_slice_matches(progress, next_task_number, stop_point_id):
        base_value = _get_slice_share(progress, next_task_number)
        if base_value is not None:
            return base_value

    tasks_in_slice = max(slice_end_task - slice_start_task + 1, 1)
    prices = distribute_value_unevenly(slice_budget, tasks_in_slice, leftover_buffer=Decimal("0.00"))
    if not prices:
        prices = [Decimal(slice_budget or Decimal("0.00"))]

    _store_active_slice(progress, slice_start_task, slice_end_task, stop_point, slice_budget, prices)
    return _get_slice_share(progress, next_task_number)


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
    return UserProductTask.objects.filter(
        user=user, 
        is_completed=True
    ).count()


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
    price_multiplier = _get_product_rate_multiplier(user)
    stop_points = list(StopPoint.objects.filter(user=user).order_by('point'))
    if daily_limit and daily_limit > 0:
        pricing_ceiling = daily_limit
    else:
        highest_stop_point = stop_points[-1].point if stop_points else next_task_number
        pricing_ceiling = max(next_task_number, highest_stop_point)

    stop_points = [sp for sp in stop_points if sp.point <= pricing_ceiling]
    upcoming_stop_points = [sp for sp in stop_points if sp.point >= next_task_number]

    current_stop_point = upcoming_stop_points[0] if upcoming_stop_points else None
    next_stop_point = upcoming_stop_points[1] if len(upcoming_stop_points) > 1 else None
    previous_cleared_stop_point = (
        StopPoint.objects
        .filter(user=user, point__lt=next_task_number, status='approved')
        .order_by('-point')
        .first()
    )
    progress = get_user_stoppoint_progress(user)
    tasks_done = next_task_number - 1

    if progress and tasks_done == 0:
        _clear_active_slice(progress)
    tasks_done = next_task_number - 1

    # Fresh day: discard any lingering slice data so pricing restarts from the
    # new recharge pool instead of an old cached budget.
    if progress and tasks_done == 0:
        _clear_active_slice(progress)

    force_fake_display = wallet.referral_earned_balance > 0 and not wallet.has_recharged
    if force_fake_display:
        spendable_balance = Decimal(wallet.current_balance).quantize(Decimal("0.01"))
        if spendable_balance <= Decimal("0.00"):
            return None, "Insufficient referral balance to continue tasks. Please recharge.", None, None, False
        update_fields = []
        if not wallet.is_fake_display_mode:
            wallet.is_fake_display_mode = True
            update_fields.append('is_fake_display_mode')
        if wallet.balance_source != 'referral':
            wallet.balance_source = 'referral'
            update_fields.append('balance_source')
        if update_fields:
            wallet.save(update_fields=update_fields)

    def finalize_task_price(task_price):
        if force_fake_display:
            return next_product, None, generate_fake_display_price(), task_price, True
        return next_product, None, task_price, task_price, False

    # --- Stop Point Trigger ---
    if current_stop_point and current_stop_point.point == next_task_number:
        snapshot = ensure_stop_point_snapshot(current_stop_point, wallet.current_balance)
        outstanding = snapshot.required_balance_remaining
        if outstanding is None:
            outstanding = Decimal(snapshot.required_balance or Decimal("0.00"))
        outstanding = Decimal(outstanding).quantize(Decimal("0.01"))

        locked_price_base = snapshot.locked_task_price or (wallet.current_balance + outstanding).quantize(Decimal("0.01"))
        locked_price = Decimal(locked_price_base).quantize(Decimal("0.01"))
        estimated_balance = snapshot.estimated_balance_snapshot
        if estimated_balance is None:
            bonus = snapshot.special_bonus_amount or Decimal("0.00")
            estimated_balance = (locked_price + bonus).quantize(Decimal("0.01"))

        if outstanding > Decimal("0.00"):
            block_reason = (
                f"{STOP_POINT_BLOCK_PREFIX}:{current_stop_point.id}:{outstanding}:"
                f"{locked_price}:{estimated_balance}"
            )
            return next_product, block_reason, locked_price, locked_price, False

        slice_budget = Decimal(current_stop_point.required_balance or Decimal("0.00"))
        slice_budget += Decimal(current_stop_point.special_bonus_amount or Decimal("0.00"))
        slice_end_task  = next_stop_point.point - 1 if next_stop_point else pricing_ceiling
        if slice_end_task < current_stop_point.point:
            slice_end_task = current_stop_point.point

        base_task_price = _consume_stop_point_slice(progress, current_stop_point, slice_budget, current_stop_point.point, slice_end_task, next_task_number)
        # Apply product rate to the base share to get final task price
        task_price = (base_task_price * price_multiplier).quantize(Decimal("0.01"))
        if task_price <= Decimal("0.00"):
            task_price = Decimal("0.01")

        return finalize_task_price(task_price)

    slicing_stop_point = current_stop_point
                                    
    # --- Normal Mode Pricing ---
    _reset_active_slice_if_stale(progress, next_task_number)

    # Determine slice bounds using the next pending stop point (if any)
    if slicing_stop_point:
        allowed_task_end = max(slicing_stop_point.point - 1, tasks_done)
    else:
        allowed_task_end = pricing_ceiling

    allowed_task_end = min(allowed_task_end, pricing_ceiling)
    tasks_in_slice = allowed_task_end - tasks_done
    if tasks_in_slice < 1:
        tasks_in_slice = 1

    # Initialize slice pool base
    slice_pool_base = Decimal("0.00")
    active_slice_stop_point = None

    # Use slice_pool_base as the budget for uneven division
    slice_budget = slice_pool_base

    if (
        price_multiplier > Decimal("0.00")
        and previous_cleared_stop_point
        and next_task_number > previous_cleared_stop_point.point
    ):
        slice_start_task = previous_cleared_stop_point.point + 1
        slice_end_task = slicing_stop_point.point - 1 if slicing_stop_point else pricing_ceiling

        if slice_start_task <= slice_end_task and next_task_number <= slice_end_task:
            slice_pool_total = Decimal(previous_cleared_stop_point.required_balance or Decimal("0.00"))
            slice_pool_total += Decimal(previous_cleared_stop_point.special_bonus_amount or Decimal("0.00"))
            slice_pool_total = slice_pool_total.quantize(Decimal("0.01"))

            if slice_pool_total > Decimal("0.00"):
                consumed_tasks = (
                    UserProductTask.objects
                    .filter(
                        user=user,
                        task_number__gte=slice_start_task,
                        task_number__lt=next_task_number,
                        price__isnull=False,
                    )
                    .values_list('price', flat=True)
                )

                base_consumed = Decimal("0.00")
                for price_amount in consumed_tasks:
                    base_consumed += _derive_base_from_price(price_amount, price_multiplier)

                remaining_base = (slice_pool_total - base_consumed).quantize(Decimal("0.01"))
                if remaining_base <= Decimal("0.00"):
                    remaining_base = Decimal("0.01")

                slice_budget = remaining_base
                tasks_in_slice = slice_end_task - (next_task_number - 1)
                if tasks_in_slice < 1:
                    tasks_in_slice = 1
                active_slice_stop_point = previous_cleared_stop_point

    if (
        slice_budget <= Decimal("0.00")
        and price_multiplier > Decimal("0.00")
        and not previous_cleared_stop_point
    ):
        initial_pool = _get_initial_pool_amount(user, wallet)
        initial_pool = Decimal(initial_pool or Decimal("0.00")).quantize(Decimal("0.01"))
        if initial_pool > Decimal("0.00"):
            slice_end_task = slicing_stop_point.point - 1 if slicing_stop_point else pricing_ceiling
            if next_task_number <= slice_end_task:
                consumed_tasks = (
                    UserProductTask.objects
                    .filter(
                        user=user,
                        task_number__lt=next_task_number,
                        price__isnull=False,
                    )
                    .values_list('price', flat=True)
                )

                base_consumed = Decimal("0.00")
                for price_amount in consumed_tasks:
                    base_consumed += _derive_base_from_price(price_amount, price_multiplier)

                remaining_base = (initial_pool - base_consumed).quantize(Decimal("0.01"))
                if remaining_base <= Decimal("0.00"):
                    remaining_base = Decimal("0.01")

                slice_budget = remaining_base
                tasks_in_slice = slice_end_task - (next_task_number - 1)
                if tasks_in_slice < 1:
                    tasks_in_slice = 1

    if slice_budget <= Decimal("0.00"):
        # Fallback: allow tasks if user has any balance but no slice budget
        if wallet.current_balance > Decimal("0.00"):
            slice_budget = Decimal("0.01")
        else:
            return None, "Insufficient balance to continue tasks. Please recharge.", None, None, False

    slice_start_task = tasks_done + 1
    slice_end_task = allowed_task_end
    base_task_price = None
    stop_point_id = active_slice_stop_point.id if active_slice_stop_point else None

    if _active_slice_matches(progress, next_task_number, stop_point_id):
        base_task_price = _get_slice_share(progress, next_task_number)

    if base_task_price is None:
        prices = distribute_value_unevenly(slice_budget, tasks_in_slice, leftover_buffer=Decimal("0.00"))
        if not prices:
            prices = [slice_budget.quantize(Decimal("0.01"))]
        _store_active_slice(progress, slice_start_task, slice_end_task, active_slice_stop_point, slice_budget, prices)
        base_task_price = _get_slice_share(progress, next_task_number)

    # Apply product rate to the base share to get final task price
    task_price = (base_task_price * price_multiplier).quantize(Decimal("0.01"))

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

    active_task = UserProductTask.objects.filter(user=user, is_completed=False).first()
    if not active_task:
        minimum_balance = Decimal("1.00")
        if wallet.current_balance < minimum_balance:
            return None, "Insufficient balance.", None, None, False

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

    stop_point_blocked = (
        isinstance(block_reason, str)
        and block_reason.startswith(f"{STOP_POINT_BLOCK_PREFIX}:")
    )

    if next_product and (not block_reason or stop_point_blocked):
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

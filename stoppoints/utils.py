from decimal import Decimal, InvalidOperation
from django.db.models import Max
from django.conf import settings
from .models import StopPoint, StopPointProgress
from products.models import UserProductTask

STOPPOINT_DEFAULT_REQUIRED = Decimal(getattr(settings, "STOPPOINT_DEFAULT_REQUIRED", "200.00"))

# -----------------------------
# Get Daily Task Limit
# -----------------------------
def get_daily_task_limit(user):
    try:
        setting = getattr(user, 'commission_setting', None)
        if setting and getattr(setting, 'daily_task_limit', None):
            return int(setting.daily_task_limit)
    except Exception:
        pass
    return 0

# -----------------------------
# Add StopPoints for User
# -----------------------------
def add_stop_points_for_user(user, stop_data_list):
    """
    Adds StopPoint objects for a user from a list of tuples.
    Each tuple can be either (point,) or (point, required_balance).
    If required_balance is omitted, use STOPPOINT_DEFAULT_REQUIRED.
    """
    added_sps = []
    skipped_entries = []
    daily_limit = get_daily_task_limit(user)
    completed_task_count = UserProductTask.objects.filter(user=user, is_completed=True).count()

    last_order = StopPoint.objects.filter(user=user).aggregate(Max('order'))['order__max'] or 0
    next_order = last_order + 1

    for data_tuple in stop_data_list:
        try:
            if isinstance(data_tuple, (list, tuple)) and len(data_tuple) >= 1:
                point = data_tuple[0]
                required_balance = data_tuple[1] if len(data_tuple) > 1 else None
            else:
                point = data_tuple
                required_balance = None
            point_int = int(point)

            if required_balance is None or str(required_balance).strip() == "":
                dynamic_required_balance = STOPPOINT_DEFAULT_REQUIRED
            else:
                dynamic_required_balance = Decimal(str(required_balance)).quantize(Decimal("0.01"))
            
            # Validation
            if not (1 <= point_int <= daily_limit):
                skipped_entries.append(f"Point {point_int} out of range (1-{daily_limit})")
                continue
            if point_int <= completed_task_count:
                skipped_entries.append(f"Point {point_int} invalid; user has completed {completed_task_count} tasks.")
                continue
            if StopPoint.objects.filter(user=user, point=point_int).exists():
                skipped_entries.append(f"Point {point_int} already exists")
                continue
            if dynamic_required_balance <= 0:
                skipped_entries.append(f"Balance for point {point_int} must be positive")
                continue

            sp = StopPoint.objects.create(
                user=user,
                point=point_int,
                required_balance=dynamic_required_balance,
                order=next_order
            )
            added_sps.append(sp)
            next_order += 1

        except (ValueError, TypeError, IndexError):
            skipped_entries.append(str(data_tuple))

    return added_sps, skipped_entries

# -----------------------------
# Update StopPoint
# -----------------------------
def update_stop_point(user, sp_id, new_point=None, new_required_balance=None):
    sp = StopPoint.objects.get(id=sp_id, user=user)
    daily_limit = get_daily_task_limit(user)

    if new_point is not None and str(new_point).strip() != "":
        new_point_int = int(new_point)
        if not (1 <= new_point_int <= daily_limit):
            raise ValueError(f"Stop point must be between 1 and {daily_limit}")
        if StopPoint.objects.filter(user=user, point=new_point_int).exclude(id=sp.id).exists():
            raise ValueError("Another stop point with this number already exists.")
        sp.point = new_point_int

    if new_required_balance is not None and str(new_required_balance).strip() != "":
        try:
            rb = Decimal(str(new_required_balance))
            if rb < 0:
                raise ValueError("Required balance must be non-negative.")
            sp.required_balance = rb
        except InvalidOperation:
            raise ValueError("Invalid required balance amount.")
    else: # Dynamically calculate if not provided
        wallet, _ = Wallet.objects.get_or_create(user=user)
        sp.required_balance = (wallet.current_balance + Decimal(random.uniform(15, 20))).quantize(Decimal("0.01"))

    sp.save()
    return sp

# -----------------------------
# Delete StopPoint
# -----------------------------
def delete_stop_point(user, stop_point_id):
    try:
        sp = StopPoint.objects.get(id=stop_point_id, user=user)
        sp.delete()
        return True, None
    except StopPoint.DoesNotExist:
        return False, "StopPoint not found."
    except Exception as e:
        return False, str(e)

# -----------------------------
# Get Next Pending StopPoint
# -----------------------------
def get_next_pending_stoppoint(user, next_task_number):
    return StopPoint.objects.filter(user=user, point__gte=next_task_number, status='pending').order_by('order').first()

# -----------------------------
# Check if Task is Allowed
# -----------------------------
def is_task_allowed(user, next_task_number):
    """
    Blocks user if at stop point and balance is insufficient.
    """
    stop_point = StopPoint.objects.filter(user=user, point=next_task_number).first()
    if stop_point:
        wallet, _ = Wallet.objects.get_or_create(user=user)
        if wallet.current_balance < stop_point.required_balance:
            gap = stop_point.required_balance - wallet.current_balance
            return False, f"StopPoint at task {stop_point.point}: insufficient balance (gap {gap}). Please recharge."
    return True, None

# -----------------------------
# Get User StopPoint Progress
# -----------------------------
def get_user_stoppoint_progress(user):
    """
    Retrieves or creates StopPointProgress object for tracking last cleared stop point.
    """
    progress, _ = StopPointProgress.objects.get_or_create(user=user)
    return progress

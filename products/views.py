import random
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
from django.db.utils import OperationalError
from types import SimpleNamespace
from django.http import JsonResponse

from balance.models import Wallet
from .models import Product, UserProductTask
from .utils import (
    complete_product_task,
    get_next_product_for_user,
    get_daily_task_limit,
    get_daily_completed_tasks,
    format_product_code,
)
from commission.models import Commission, CommissionSetting

from stoppoints.models import StopPoint
from stoppoints.utils import get_next_pending_stoppoint

@login_required
def products_view(request):
    user = request.user
    wallet, _ = Wallet.objects.get_or_create(user=user)
    tasks_completed_total = UserProductTask.objects.filter(user=user, is_completed=True).count()
    tasks_completed_today = get_daily_completed_tasks(user)
    next_task_number = tasks_completed_total + 1
    daily_limit_value = get_daily_task_limit(user)
    display_task_position = tasks_completed_today + 1

    # Get next product with fake mode support
    result = get_next_product_for_user(user)
    
    # Handle different return formats (old and new)
    if len(result) == 5:  # New format with fake mode support
        next_product, block_reason, display_price, real_price, is_fake_mode = result
    else:  # Old format fallback
        next_product, block_reason, display_price = result
        real_price = display_price
        is_fake_mode = False
    
    can_proceed = block_reason is None

    active_product_session_key = f"stop_point_active_product_{user.id}"
    active_identifier_session_key = f"stop_point_active_identifier_{user.id}"

    current_stop_point = None
    stop_point_identifier = None

    if block_reason and "Recharge required" in block_reason:
        current_stop_point = StopPoint.objects.filter(user=user, point=next_task_number).first()
        stop_point_identifier = current_stop_point.id if current_stop_point else f"task_{next_task_number}"
        pinned_product_id = request.session.get(active_product_session_key)
        pinned_identifier = request.session.get(active_identifier_session_key)
        if pinned_product_id and str(pinned_identifier) == str(stop_point_identifier):
            pinned_product = Product.objects.filter(id=pinned_product_id).first()
            if pinned_product:
                next_product = pinned_product
        elif pinned_product_id or pinned_identifier:
            removed_product = request.session.pop(active_product_session_key, None)
            removed_identifier = request.session.pop(active_identifier_session_key, None)
            if removed_product is not None or removed_identifier is not None:
                request.session.modified = True
    else:
        removed_product = request.session.pop(active_product_session_key, None)
        removed_identifier = request.session.pop(active_identifier_session_key, None)
        if removed_product is not None or removed_identifier is not None:
            request.session.modified = True

    # --- Handle task completion POST request ---
    if request.method == "POST" and "next_product" in request.POST:
        task_obj = UserProductTask.objects.filter(user=user, product=next_product, is_completed=False).first()
        if not can_proceed:
            messages.warning(request, block_reason or "Cannot proceed to next task.")
        elif not task_obj:
            messages.warning(request, "Task is not available or already completed.")
        else:
            try:
                result = complete_product_task(user, task_obj)
                if result.get("warning"):
                    messages.warning(request, result.get("warning"))
                else:
                    if task_obj.is_fake_mode_task:
                        completed_count = UserProductTask.objects.filter(user=user, is_completed=True).count()
                        daily_limit = daily_limit_value
            except OperationalError:
                messages.error(request, "System is busy processing tasks. Please retry in a moment.")
        return redirect("products:products")

    # --- Create or fetch the task object for display ---
    task_obj = None
    if next_product:
        task_obj = UserProductTask.objects.filter(user=user, product=next_product, is_completed=False).first()
        defaults = {
            'task_number': next_task_number,
            'is_fake_mode_task': is_fake_mode,
            'price': real_price if is_fake_mode else display_price,
            'fake_display_price': display_price if is_fake_mode else None,
            'real_price': real_price,
            'pricing_snapshot_daily_limit': daily_limit_value
        }

        if not task_obj and can_proceed:
            try:
                task_obj, _ = UserProductTask.objects.get_or_create(
                    user=user,
                    product=next_product,
                    is_completed=False,
                    defaults=defaults
                )
            except OperationalError:
                messages.error(request, "System is busy processing tasks. Please retry in a moment.")
                return redirect("products:products")
        elif not task_obj:
            task_obj = SimpleNamespace(**defaults, product=next_product)

    # --- Display commission calculation ---
    display_commission = Decimal("0.00")
    if task_obj:
        # Convert to commission
        user_commission_setting, _ = CommissionSetting.objects.get_or_create(user=user)
        display_commission = (task_obj.price * user_commission_setting.product_rate / 100).quantize(Decimal("0.01"))

    # --- Refresh wallet totals for display ---
    wallet.product_commission = Commission.objects.filter(user=user, commission_type='self').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    wallet.referral_commission = Commission.objects.filter(user=user, commission_type='referral').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # --- Today's commissions ---
    today = timezone.now().date()
    today_product_commission = Commission.objects.filter(user=user, commission_type='self', created_at__date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    today_referral_commission = Commission.objects.filter(user=user, commission_type='referral', created_at__date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # --- Task completion flag ---
    can_complete_task = can_proceed and task_obj is not None

    # --- Determine StopPoint block and all products completion ---
    is_stopped_due_to_balance = False
    all_products_completed = False
    stop_point_info = None
    daily_limit_unset = False
    daily_limit_reached = False
    no_products_available = False

    if next_product is None:
        reason_lower = block_reason.lower() if block_reason else ""
        if "admin must set your daily task limit" in reason_lower:
            daily_limit_unset = True
        elif "reached your daily task limit" in reason_lower or (
            "daily task limit" in reason_lower and "reach" in reason_lower
        ):
            all_products_completed = True
            daily_limit_reached = True
        elif "daily task limit" in reason_lower and not reason_lower.strip():
            daily_limit_unset = True
        elif "no products available" in reason_lower:
            no_products_available = True
        elif reason_lower:
            # Fallback: treat unknown reasons as no products available
            no_products_available = True
        else:
            # When no specific block reason is provided, treat as no products available
            no_products_available = True
    elif block_reason and "Recharge required" in block_reason:
        is_stopped_due_to_balance = True

    if all_products_completed and tasks_completed_today == 0:
        # Guard against showing completion modal when no tasks have actually been finished today
        all_products_completed = False
        daily_limit_reached = False

    recharge_gap = Decimal("0.00")
    if is_stopped_due_to_balance:
        if current_stop_point is None:
            current_stop_point = StopPoint.objects.filter(user=user, point=next_task_number).first()
        required_balance_value = Decimal("0.00")
        if current_stop_point and current_stop_point.required_balance is not None:
            required_balance_value = Decimal(current_stop_point.required_balance)

        task_price_snapshot = None
        if display_price is not None:
            task_price_snapshot = Decimal(display_price)
        elif real_price is not None:
            task_price_snapshot = Decimal(real_price)

        if task_price_snapshot is None and next_product:
            price_attr = getattr(next_product, "price", None)
            if price_attr is not None:
                task_price_snapshot = Decimal(price_attr)

        required_balance_value = required_balance_value.quantize(Decimal("0.01")) if required_balance_value else Decimal("0.00")
        task_price_snapshot = task_price_snapshot.quantize(Decimal("0.01")) if task_price_snapshot else Decimal("0.00")
        minimum_required_balance = max(required_balance_value, task_price_snapshot).quantize(Decimal("0.01"))

        if stop_point_identifier is None:
            stop_point_identifier = current_stop_point.id if current_stop_point else f"task_{next_task_number}"
        stop_point_identifier_str = str(stop_point_identifier)
        session_prefix = f"stop_point_{user.id}_{stop_point_identifier_str}"
        target_key = f"{session_prefix}_target"
        required_key = f"{session_prefix}_required"
        start_balance_key = f"{session_prefix}_start_balance"
        last_balance_key = f"{session_prefix}_last_balance"
        recharged_key = f"{session_prefix}_recharged_total"
        display_price_key = f"{session_prefix}_display_price"
        product_key = f"{session_prefix}_product_id"

        session_changed = False
        if target_key not in request.session:
            request.session[target_key] = str(minimum_required_balance)
            session_changed = True
        if required_key not in request.session:
            request.session[required_key] = str(required_balance_value)
            session_changed = True

        current_balance_value = wallet.current_balance.quantize(Decimal("0.01"))

        if start_balance_key not in request.session:
            request.session[start_balance_key] = str(current_balance_value)
            request.session[last_balance_key] = str(current_balance_value)
            request.session[recharged_key] = "0.00"
            locked_display_price = (required_balance_value + current_balance_value).quantize(Decimal("0.01"))
            request.session[display_price_key] = str(locked_display_price)
            session_changed = True

        product_id_str = str(getattr(next_product, "id", "")) if next_product else ""
        if product_id_str:
            if request.session.get(product_key) != product_id_str:
                request.session[product_key] = product_id_str
                session_changed = True
            if request.session.get(active_product_session_key) != product_id_str:
                request.session[active_product_session_key] = product_id_str
                session_changed = True
        if request.session.get(active_identifier_session_key) != stop_point_identifier_str:
            request.session[active_identifier_session_key] = stop_point_identifier_str
            session_changed = True

        base_balance_value = Decimal(request.session.get(start_balance_key, str(current_balance_value))).quantize(Decimal("0.01"))
        last_balance_value = Decimal(request.session.get(last_balance_key, str(current_balance_value))).quantize(Decimal("0.01"))
        recharged_total = Decimal(request.session.get(recharged_key, "0.00")).quantize(Decimal("0.01"))

        balance_delta = (current_balance_value - last_balance_value).quantize(Decimal("0.01"))
        if balance_delta > Decimal("0.00"):
            recharged_total += balance_delta
            request.session[recharged_key] = str(recharged_total)
            session_changed = True
        if balance_delta != Decimal("0.00"):
            request.session[last_balance_key] = str(current_balance_value)
            session_changed = True

        if session_changed:
            request.session.modified = True

        required_remaining = (required_balance_value - recharged_total).quantize(Decimal("0.01"))
        if required_remaining < Decimal("0.00"):
            required_remaining = Decimal("0.00")

        display_price_value = Decimal(
            request.session.get(
                display_price_key,
                str((required_balance_value + base_balance_value).quantize(Decimal("0.01")))
            )
        ).quantize(Decimal("0.01"))

        recharge_gap = required_remaining

        bonus_percent_value = None
        if current_stop_point:
            ordered_points = list(
                StopPoint.objects.filter(user=user).order_by("point").values_list("id", flat=True)
            )
            try:
                stop_index = ordered_points.index(current_stop_point.id)
            except ValueError:
                stop_index = -1
            if stop_index % 2 == 0:  # show on 1st, 3rd, ... stop points
                bonus_percent_value = random.randrange(15, 50, 2)

        stop_point_info = {
            "product_code": format_product_code(getattr(next_product, "product_code", "")) if next_product else "",
            "current_date": timezone.now(),
            "balance_gap": recharge_gap,
            "required_balance": recharge_gap,
            "current_balance": current_balance_value,
            "next_product_price": display_price_value,
            "bonus_percent": bonus_percent_value,
        }

        if required_remaining == Decimal("0.00"):
            is_stopped_due_to_balance = False
            block_reason = None
            can_proceed = True
            stop_point_info = None
            request.session.pop(target_key, None)
            request.session.pop(required_key, None)
            request.session.pop(start_balance_key, None)
            request.session.pop(last_balance_key, None)
            request.session.pop(recharged_key, None)
            request.session.pop(display_price_key, None)
            request.session.pop(product_key, None)
            request.session.pop(active_product_session_key, None)
            request.session.pop(active_identifier_session_key, None)
            request.session.modified = True
        else:
            block_reason = f"Recharge required {recharge_gap}"
            can_proceed = False

    # Debug information
    print(f"[DEBUG] is_fake_mode: {is_fake_mode}")
    print(f"[DEBUG] wallet.balance_source: {wallet.balance_source}")
    print(f"[DEBUG] display_price: {display_price}, real_price: {real_price}")
    print(f"[DEBUG] wallet.referral_earned_balance: {wallet.referral_earned_balance}")
    
    # Set up price display variables
    display_price_value = display_price if is_fake_mode else (getattr(task_obj, 'price', 0) if task_obj else 0)
    real_price_value = real_price if is_fake_mode else (getattr(task_obj, 'price', 0) if task_obj else 0)
    
    first_task_ready = False
    if task_obj and tasks_completed_today == 0 and not daily_limit_reached and not daily_limit_unset:
        first_task_ready = True

    context = {
        "product": next_product,
        "task": task_obj,
        "display_task_number": display_task_position,
        "daily_limit": daily_limit_value,
        "can_proceed": can_proceed,
        "can_complete_task": can_complete_task,
        "block_reason": block_reason,
        "is_stopped_at_point": is_stopped_due_to_balance,
        "all_products_completed": all_products_completed,
        "recharge_gap": recharge_gap,
        "stop_point_info": stop_point_info,
        
        # Wallet and commission data
        "wallet": wallet,  # Pass the entire wallet object
        "current_balance": wallet.current_balance,
        "product_commission": wallet.product_commission,
        "referral_commission": wallet.referral_commission,
        "total_balance": wallet.cumulative_total,
        "daily_limit_unset": daily_limit_unset,
        "daily_limit_reached": daily_limit_reached,
        "no_products_available": no_products_available,
        "tasks_completed_count": tasks_completed_today,
        "first_task_ready": first_task_ready,

        # Fake mode pricing context
        "is_fake_mode": is_fake_mode,
        "fake_display_price": display_price if is_fake_mode else None,
        "real_price": real_price,
    }

    return render(request, "products/products.html", context)
@login_required
def get_balance(request):
    user = request.user
    wallet, _ = Wallet.objects.get_or_create(user=user)

    today = timezone.now().date()
    today_product_commission = Commission.objects.filter(user=user, commission_type='self', created_at__date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    today_referral_commission = Commission.objects.filter(user=user, commission_type='referral', created_at__date=today).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    data = {
        'current_balance': wallet.current_balance,
        'product_commission': wallet.product_commission,
        'referral_commission': wallet.referral_commission,
        'total_balance': wallet.cumulative_total,
        'today_product_commission': today_product_commission,
        'today_referral_commission': today_referral_commission,
        'today_commission': today_product_commission + today_referral_commission,
    }
    return JsonResponse(data)


@login_required
def regulation_policy(request):
    return render(request, "products/regulation_policy.html")

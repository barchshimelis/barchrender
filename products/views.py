import random
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
from django.db.utils import OperationalError
from types import SimpleNamespace
from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.template.loader import render_to_string

from balance.models import Wallet
from .models import Product, UserProductTask
from .utils import (
    complete_product_task,
    get_next_product_for_user,
    get_daily_task_limit,
    get_daily_completed_tasks,
    format_product_code,
    STOP_POINT_BLOCK_PREFIX,
)
from commission.models import Commission, CommissionSetting

from stoppoints.models import StopPoint
from stoppoints.utils import get_next_pending_stoppoint


def parse_stop_point_block_reason(block_reason):
    if not block_reason or not block_reason.startswith(f"{STOP_POINT_BLOCK_PREFIX}:"):
        return None
    try:
        _, stop_point_id, remaining, locked_price, estimated_balance = block_reason.split(":")
        return {
            "stop_point_id": int(stop_point_id),
            "remaining": Decimal(remaining),
            "locked_price": Decimal(locked_price),
            "estimated_balance": Decimal(estimated_balance),
        }
    except (ValueError, InvalidOperation):
        return None


def _calculate_lucky_order_display_percent(stop_point):
    if not stop_point:
        return None

    seed_input = f"{stop_point.id}-{stop_point.point}-{stop_point.user_id}"
    seeded_random = random.Random(seed_input)
    return seeded_random.randint(12, 49)


def _is_ajax_request(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _build_products_state(user):
    wallet, _wallet_created = Wallet.objects.get_or_create(user=user)
    commission_setting, _commission_setting_created = CommissionSetting.objects.get_or_create(user=user)
    Decimal(str(commission_setting.product_rate or Decimal("0.00"))).quantize(Decimal("0.01"))
    tasks_completed_total = UserProductTask.objects.filter(user=user, is_completed=True).count()
    tasks_completed_today = get_daily_completed_tasks(user)
    next_task_number = tasks_completed_total + 1
    daily_limit_value = get_daily_task_limit(user)
    display_task_position = tasks_completed_today + 1

    result = get_next_product_for_user(user)

    if len(result) == 5:
        next_product, block_reason, display_price, real_price, is_fake_mode = result
    else:
        next_product, block_reason, display_price = result
        real_price = display_price
        is_fake_mode = False

    can_proceed = block_reason is None

    stop_point_block = parse_stop_point_block_reason(block_reason)
    current_stop_point = None

    task_obj = None
    if next_product:
        task_obj = UserProductTask.objects.filter(user=user, product=next_product, is_completed=False).first()
        defaults = {
            "task_number": next_task_number,
            "is_fake_mode_task": is_fake_mode,
            "price": real_price if is_fake_mode else display_price,
            "fake_display_price": display_price if is_fake_mode else None,
            "real_price": real_price,
            "pricing_snapshot_daily_limit": daily_limit_value,
        }

        if not task_obj and can_proceed:
            try:
                task_obj, _task_created = UserProductTask.objects.get_or_create(
                    user=user,
                    product=next_product,
                    is_completed=False,
                    defaults=defaults,
                )
            except OperationalError:
                messages.error(user, _("System is busy processing tasks. Please retry in a moment."))
                return redirect("products:products")
        elif not task_obj:
            task_obj = SimpleNamespace(**defaults, product=next_product)

    display_commission = Decimal("0.00")
    if isinstance(task_obj, UserProductTask):
        display_commission = (task_obj.price * commission_setting.product_rate / 100).quantize(Decimal("0.01"))

    display_product_price = None
    if next_product:
        completed_withdrawals = getattr(wallet, "completed_withdrawals", 0) or 0
        if completed_withdrawals >= 2:
            price_floor, price_ceiling = 1000, 2300
        elif completed_withdrawals >= 1:
            price_floor, price_ceiling = 500, 1200
        else:
            price_floor, price_ceiling = 150, 500

        seeded_random = random.Random(
            f"{user.id}-{next_product.id}-{display_task_position}-{completed_withdrawals}"
        )
        display_product_price = Decimal(
            seeded_random.randint(price_floor, price_ceiling)
        ).quantize(Decimal("0.01"))

        stop_point_override = (
            StopPoint.objects
            .filter(user=user, point=next_task_number)
            .exclude(status="rejected")
            .only("locked_task_price", "status")
            .first()
        )
        if stop_point_override and stop_point_override.locked_task_price is not None:
            display_product_price = stop_point_override.locked_task_price

    wallet.product_commission = (
        Commission.objects.filter(user=user, commission_type="self").aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    wallet.referral_commission = (
        Commission.objects.filter(user=user, commission_type="referral").aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    today = timezone.now().date()
    today_product_commission = (
        Commission.objects.filter(user=user, commission_type="self", created_at__date=today).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    today_referral_commission = (
        Commission.objects.filter(user=user, commission_type="referral", created_at__date=today).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    can_complete_task = can_proceed and task_obj is not None

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
            no_products_available = True
        else:
            no_products_available = True
    elif block_reason and "Recharge required" in block_reason:
        is_stopped_due_to_balance = True

    if all_products_completed and tasks_completed_today == 0:
        all_products_completed = False
        daily_limit_reached = False

    recharge_gap = Decimal("0.00")
    if stop_point_block:
        current_stop_point = StopPoint.objects.filter(id=stop_point_block["stop_point_id"]).first()
        is_stopped_due_to_balance = True
        can_proceed = False
        recharge_gap = stop_point_block["remaining"].quantize(Decimal("0.01"))
        block_reason = f"Recharge required {recharge_gap}"

        special_bonus_value = None
        lucky_order_enabled = False
        if current_stop_point:
            raw_bonus = getattr(current_stop_point, "special_bonus_amount", None)
            if raw_bonus not in (None, ""):
                try:
                    special_bonus_value = Decimal(str(raw_bonus)).quantize(Decimal("0.01"))
                except (InvalidOperation, TypeError):
                    special_bonus_value = None
            lucky_order_enabled = bool(getattr(current_stop_point, "lucky_order_enabled", False))

        lucky_order_bonus = None
        if lucky_order_enabled:
            if special_bonus_value is not None:
                lucky_order_bonus = special_bonus_value
            elif stop_point_block:
                lucky_order_bonus = (
                    stop_point_block["estimated_balance"] - stop_point_block["locked_price"]
                ).quantize(Decimal("0.01"))

        product_name = ""
        if next_product:
            product_name = (
                getattr(next_product, "name", "")
                or getattr(next_product, "product_code", "")
                or getattr(next_product, "code", "")
            )

        stop_point_info = {
            "product_name": product_name,
            "current_date": timezone.now(),
            "balance_gap": recharge_gap,
            "required_balance": recharge_gap,
            "current_balance": wallet.current_balance.quantize(Decimal("0.01")),
            "next_product_price": stop_point_block["locked_price"],
            "estimated_total_balance": stop_point_block["estimated_balance"],
            "special_bonus_amount": special_bonus_value,
            "lucky_order_enabled": lucky_order_enabled,
            "lucky_order_bonus": lucky_order_bonus,
        }

        display_product_price = stop_point_info["next_product_price"]

    print(f"[DEBUG] is_fake_mode: {is_fake_mode}")
    print(f"[DEBUG] wallet.balance_source: {wallet.balance_source}")
    print(f"[DEBUG] display_price: {display_price}, real_price: {real_price}")
    print(f"[DEBUG] wallet.referral_earned_balance: {wallet.referral_earned_balance}")

    display_price_value = display_price if is_fake_mode else (getattr(task_obj, "price", 0) if task_obj else 0)
    real_price_value = real_price if is_fake_mode else (getattr(task_obj, "price", 0) if task_obj else 0)

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
        "wallet": wallet,
        "current_balance": wallet.current_balance,
        "product_commission": wallet.product_commission,
        "referral_commission": wallet.referral_commission,
        "daily_limit_unset": daily_limit_unset,
        "daily_limit_reached": daily_limit_reached,
        "no_products_available": no_products_available,
        "tasks_completed_count": tasks_completed_today,
        "first_task_ready": first_task_ready,
        "is_fake_mode": is_fake_mode,
        "fake_display_price": display_price if is_fake_mode else None,
        "real_price": real_price,
        "today_product_commission": today_product_commission,
        "today_referral_commission": today_referral_commission,
        "display_commission": display_commission,
        "display_product_price": display_product_price,
    }

    task_record = task_obj if isinstance(task_obj, UserProductTask) else None

    return {
        "context": context,
        "next_product": next_product,
        "task_record": task_record,
        "can_proceed": can_proceed,
        "daily_limit_value": daily_limit_value,
    }


def _handle_next_product_submission(request, state):
    user = request.user
    task_obj = state.get("task_record")
    can_proceed = state.get("can_proceed")
    block_reason = state.get("context", {}).get("block_reason")
    success = False

    if not can_proceed:
        messages.warning(request, block_reason or _("Cannot proceed to next task."))
    elif not task_obj:
        messages.warning(request, _("Task is not available or already completed."))
    else:
        try:
            result = complete_product_task(user, task_obj)
            warning = result.get("warning")
            if warning:
                messages.warning(request, warning)
            else:
                success = True
        except OperationalError:
            messages.error(
                request,
                _("System is busy processing tasks. Please retry in a moment."),
            )

    if _is_ajax_request(request):
        updated_state = _build_products_state(user)
        task_panel_html = render_to_string(
            "products/partials/task_panel.html",
            updated_state["context"],
            request=request,
        )
        context_flags = updated_state["context"]

        payload = {
            "success": success,
            "task_panel_html": task_panel_html,
            "all_products_completed": context_flags.get("all_products_completed"),
            "daily_limit_unset": context_flags.get("daily_limit_unset"),
            "daily_limit_reached": context_flags.get("daily_limit_reached"),
            "no_products_available": context_flags.get("no_products_available"),
            "can_proceed": context_flags.get("can_proceed"),
        }
        return JsonResponse(payload)

    return redirect("products:products")


@login_required
def products_view(request):
    state = _build_products_state(request.user)
    context = state["context"]

    if request.method == "POST" and "next_product" in request.POST:
        return _handle_next_product_submission(request, state)

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
        'today_product_commission': today_product_commission,
        'today_referral_commission': today_referral_commission,
        'today_commission': today_product_commission + today_referral_commission,
    }
    return JsonResponse(data)


@login_required
def regulation_policy(request):
    return render(request, "products/regulation_policy.html")

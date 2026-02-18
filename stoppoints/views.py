def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value is None:
        return False
    return bool(value)
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from decimal import Decimal, InvalidOperation
import json
import logging

from accounts.models import CustomUser
from .models import StopPoint
from .utils import add_stop_points_for_user, update_stop_point, delete_stop_point

logger = logging.getLogger(__name__)

def is_admin(user):
    return user.is_authenticated and user.role == "admin"


@login_required
@user_passes_test(is_admin)
def add_stop_points_view(request, user_id):
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)
    is_ajax = "application/json" in request.headers.get("Content-Type", "")

    if getattr(user, "role", None) != "user":
        error_message = f"Target user (id={user_id}) is not a regular user."
        if is_ajax:
            return JsonResponse({"success": False, "error": error_message}, status=400)
        messages.error(request, error_message)
        return redirect("accounts:admin_dashboard")

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            points = data.get("stop_order", [])
            required_recharges = data.get("required_recharge", [])
            special_bonuses = data.get("special_bonus_amount", [])
            lucky_flags = data.get("lucky_order_enabled", [])
            if not isinstance(points, list):
                points = [points]
            if not isinstance(required_recharges, list):
                required_recharges = [required_recharges] if required_recharges not in (None, "") else []
            if not isinstance(special_bonuses, list):
                special_bonuses = [special_bonuses] if special_bonuses not in (None, "") else []
            if not isinstance(lucky_flags, list):
                lucky_flags = [lucky_flags] if lucky_flags not in (None, "") else []
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        if not points:
            return JsonResponse({"success": False, "error": "Points must be provided."}, status=400)

        stop_data = []
        for idx, point_value in enumerate(points):
            required_value = required_recharges[idx] if idx < len(required_recharges) else None
            special_value = special_bonuses[idx] if idx < len(special_bonuses) else None
            lucky_value = lucky_flags[idx] if idx < len(lucky_flags) else False
            stop_data.append((point_value, required_value, special_value, _parse_bool(lucky_value)))

        added_points, skipped_entries = [], []
        if stop_data:
            try:
                added_list, skipped_list = add_stop_points_for_user(user, stop_data)
                for sp in (added_list or []):
                    added_points.append({
                        "id": sp.id,
                        "point": sp.point,
                        "required_balance": str(sp.required_balance), # Use required_balance from the created StopPoint
                        "special_bonus_amount": str(sp.special_bonus_amount) if sp.special_bonus_amount is not None else "",
                        "lucky_order_enabled": sp.lucky_order_enabled,
                    })
                skipped_entries.extend(skipped_list or [])
            except Exception as e:
                logger.exception("add_stop_points_for_user failed: %s", e)
                return JsonResponse({"success": False, "error": "Server error adding stop points."}, status=500)

        if not added_points and skipped_entries:
             return JsonResponse({"success": False, "error": ", ".join(skipped_entries)})

        return JsonResponse({"success": True, "added": added_points, "skipped": skipped_entries})
    
    return redirect("accounts:admin_dashboard")


@login_required
@user_passes_test(is_admin)
def update_stop_point_view(request, user_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"}, status=405)

    try:
        user = get_object_or_404(CustomUser, id=user_id, role="user")
        data = json.loads(request.body)
        sp_id = data.get("stop_point_id")
        new_point = data.get("new_point", "").strip()
        new_required_balance = data.get("new_required_recharge", "").strip()
        new_special_bonus_amount = data.get("new_special_bonus_amount", "").strip()
        new_lucky_order_enabled = _parse_bool(data.get("new_lucky_order_enabled", None)) if "new_lucky_order_enabled" in data else None

        sp = update_stop_point(
            user,
            sp_id,
            new_point=int(new_point) if new_point else None,
            new_required_balance=new_required_balance if new_required_balance else None,
            new_special_bonus_amount=new_special_bonus_amount if new_special_bonus_amount != "" else "",
            new_lucky_order_enabled=new_lucky_order_enabled
        )
        return JsonResponse({
            "success": True,
            "message": "Stop point updated.",
            "point": {
                "id": sp.id,
                "point": sp.point,
                "required_balance": str(sp.required_balance),
                "special_bonus_amount": str(sp.special_bonus_amount) if sp.special_bonus_amount is not None else "",
                "lucky_order_enabled": sp.lucky_order_enabled,
            }
        })
    except StopPoint.DoesNotExist:
        return JsonResponse({"success": False, "error": "StopPoint not found."}, status=404)
    except (ValueError, InvalidOperation) as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)
    except Exception as e:
        logger.error(f"Error updating stop point: {e}")
        return JsonResponse({"success": False, "error": "An unexpected error occurred."}, status=500)


@login_required
@user_passes_test(is_admin)
def delete_stop_point_view(request, user_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method"}, status=405)
    
    try:
        user = get_object_or_404(CustomUser, id=user_id, role="user")
        data = json.loads(request.body)
        sp_id = data.get("stop_point_id")

        success, error = delete_stop_point(user, sp_id)

        if success:
            return JsonResponse({"success": True, "message": "Stop point deleted."}, status=200)
        else:
            return JsonResponse({"success": False, "error": error}, status=400)
    except CustomUser.DoesNotExist:
        return JsonResponse({"success": False, "error": "User not found."}, status=404)
    except Exception as e:
        logger.error(f"Error deleting stop point: {e}")
        return JsonResponse({"success": False, "error": "An unexpected error occurred."}, status=500)

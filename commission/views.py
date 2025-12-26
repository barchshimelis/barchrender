import json
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import CommissionSetting
from accounts.models import CustomUser
from accounts.utils import is_admin

# -----------------------------
# Product Commission Views
# -----------------------------

@login_required
@user_passes_test(is_admin)
def set_commission(request, user_id):
    """
    Admin sets a user's product commission rate.
    """
    user = get_object_or_404(CustomUser, id=user_id)

    if request.method == "POST":
        rate = request.POST.get("commission_rate")
        if not rate:
            messages.error(request, "Commission rate is required.")
            return redirect("accounts:admin_dashboard")

        rate = Decimal(rate)
        commission_setting, _ = CommissionSetting.objects.get_or_create(user=user)
        commission_setting.product_rate = rate
        commission_setting.save(update_fields=["product_rate"])

        messages.success(request, f"Product commission for {user.username} set to {rate}%.")
        return redirect("accounts:admin_dashboard")


@login_required
@user_passes_test(is_admin)
def update_user_commission(request):
    """
    AJAX: update product commission rate.
    """
    if request.method == "POST":
        data = json.loads(request.body)
        user_id = data.get("user_id")
        rate = Decimal(data.get("rate", 0))

        try:
            user = CustomUser.objects.get(id=user_id)
            setting, _ = CommissionSetting.objects.get_or_create(user=user)
            setting.product_rate = rate
            setting.save(update_fields=["product_rate"])
            return JsonResponse({"success": True})
        except CustomUser.DoesNotExist:
            return JsonResponse({"success": False, "error": "User not found"})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required
@user_passes_test(lambda u: u.is_superuser or u.role in ['superadmin', 'admin'])
def update_user_referral_commission(request):
    """
    AJAX: update referral commission rate for a user.
    """
    try:
        data = json.loads(request.body)
        referee_id = data.get("user_id")
        rate = Decimal(data.get("rate", 0))

        referee = CustomUser.objects.get(id=referee_id)
        referrer = referee.referred_by

        if not referrer:
            return JsonResponse({"success": False, "error": "Selected user has no referrer."})

        setting, _ = CommissionSetting.objects.get_or_create(user=referrer)
        setting.referral_rate = rate
        setting.save(update_fields=["referral_rate"])

        return JsonResponse({"success": True, "referrer": referrer.username})
    except CustomUser.DoesNotExist:
        return JsonResponse({"success": False, "error": "User not found."})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

from commission.models import CommissionSetting
from products.models import UserProductTask
from stoppoints.models import StopPoint, StopPointProgress


def reset_user_cycle_state(user):
    """Clear all admin-configured state so the next cycle starts empty."""
    UserProductTask.objects.filter(user=user).delete()
    StopPoint.objects.filter(user=user).delete()
    StopPointProgress.objects.filter(user=user).delete()
    CommissionSetting.objects.filter(user=user).delete()

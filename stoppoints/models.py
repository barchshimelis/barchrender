# stoppoints/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone

class StopPoint(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    point = models.PositiveIntegerField(default=0)  # Task milestone
    required_balance = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=[('pending','Pending'),('approved','Approved'),('rejected','Rejected')], default='pending')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username} StopPoint {self.point}"


class StopPointProgress(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    last_cleared = models.ForeignKey(StopPoint, on_delete=models.SET_NULL, null=True, blank=True)
    is_stopped = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} Progress"

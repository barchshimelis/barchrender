# stoppoints/models.py
from decimal import Decimal

from django.db import models
from django.conf import settings
from django.utils import timezone

class StopPoint(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    point = models.PositiveIntegerField(default=0)  # Task milestone
    required_balance = models.DecimalField(max_digits=12, decimal_places=2)
    special_bonus_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional one-time flat bonus amount awarded when this stop point product is completed.",
    )
    bonus_disbursed = models.BooleanField(
        default=False,
        help_text="Tracks whether the stop-point bonus has already been credited to the wallet.",
    )
    bonus_disbursed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the stop-point bonus was credited to the wallet.",
    )
    recharged_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Cumulative recharge amount applied toward this stop point's requirement.",
    )
    required_balance_remaining = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Outstanding amount still needed to clear this stop point.",
    )
    locked_task_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Snapshot of the next task price captured when the stop point triggers.",
    )
    estimated_balance_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Projected balance shown to the user (includes bonus) when the stop point triggers.",
    )
    lucky_order_enabled = models.BooleanField(
        default=False,
        help_text="If enabled, show lucky-order bonus messaging when this stop point triggers."
    )
    status = models.CharField(max_length=10, choices=[('pending','Pending'),('approved','Approved'),('rejected','Rejected')], default='pending')
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username} StopPoint {self.point}"


class StopPointProgress(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    last_cleared = models.ForeignKey(StopPoint, on_delete=models.SET_NULL, null=True, blank=True)
    is_stopped = models.BooleanField(default=False)
    active_slice_pool_base = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    active_slice_start_task = models.PositiveIntegerField(null=True, blank=True)
    active_slice_end_task = models.PositiveIntegerField(null=True, blank=True)
    active_slice_stop_point = models.ForeignKey(
        StopPoint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_slice_progress",
    )
    active_slice_shares = models.JSONField(null=True, blank=True, help_text="Ordered base-share list for the current slice.")

    def __str__(self):
        return f"{self.user.username} Progress"

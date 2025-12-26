from django.conf import settings
from django.db import models


class Notification(models.Model):
    CATEGORY_CHOICES = [
        ("user_register", "User Registration"),
        ("withdraw_request", "Withdrawal Request"),
        ("withdraw_approved", "Withdrawal Approved"),
        ("recharge_request", "Recharge Request"),
        ("general", "General"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=150)
    message = models.TextField()
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default="general")
    target_url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} -> {self.recipient}"


class AdminDashboardEvent(models.Model):
    EVENT_CHOICES = [
        ("recharge_request", "Recharge Request"),
        ("wallet_bind", "Wallet Bound"),
        ("withdraw_request", "Withdrawal Requested"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_events",
    )
    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES)
    message = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_event_type_display()} for {self.user.username}"

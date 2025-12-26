from decimal import Decimal

from django.conf import settings
from django.db import models


# -----------------------------
# Commission Settings
# -----------------------------
class CommissionSetting(models.Model):
    """
    Admin sets product and referral commission rates per user.
    Each user can have only one setting row.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commission_setting",
    )
    product_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )  # percentage 0-100
    referral_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )  # percentage 0-100
    daily_task_limit = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Commission Setting"
        verbose_name_plural = "Commission Settings"

    def __str__(self) -> str:
        return (
            f"{self.user.username} - Product Commission: {self.product_rate}% | "
            f"Referral Commission: {self.referral_rate}%"
        )


# -----------------------------
# Commission Records
# -----------------------------
class Commission(models.Model):
    """
    Stores awarded commission records.

    Uniqueness constraint prevents creating duplicate commission rows for the
    same (user, product_name, commission_type, triggered_by) tuple.
    """
    COMMISSION_TYPES = (("self", "Self Earned"), ("referral", "Referral Earned"))

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commissions",
        db_index=True,
    )
    product_name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    commission_type = models.CharField(max_length=10, choices=COMMISSION_TYPES, default="self", db_index=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_commissions",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Commission"
        verbose_name_plural = "Commissions"

        # Ordering: newest first is usually convenient
        ordering = ["-created_at"]

        # Indexes for the commonly queried fields
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["triggered_by"]),
            models.Index(fields=["commission_type"]),
            models.Index(fields=["created_at"]),
        ]

        # Prevent duplicate commission records for the same trigger.
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product_name", "commission_type", "triggered_by"],
                name="unique_commission_per_trigger",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.product_name} - Commission: {self.amount:.2f} ({self.commission_type})"
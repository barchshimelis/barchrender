# balance/models.py

from django.db import models
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings

User = get_user_model()

class Wallet(models.Model):
    BALANCE_SOURCE_CHOICES = [
        ('recharge', 'Recharge Balance'),
        ('referral', 'Referral Balance'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    product_commission = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    referral_commission = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Fake Display Mode fields
    referral_earned_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_fake_display_mode = models.BooleanField(default=False)
    fake_mode_started_at = models.DateTimeField(null=True, blank=True)
    
    # New fields
    balance_source = models.CharField(
        max_length=10,
        choices=BALANCE_SOURCE_CHOICES,
        default='recharge'
    )
    has_recharged = models.BooleanField(
        default=False,
        help_text="True if user has ever made a recharge"
    )
    completed_withdrawals = models.PositiveIntegerField(default=0)
    info_alert_wallet = models.BooleanField(default=False)
    info_alert_day = models.BooleanField(default=False)

    def add_recharge(self, amount):
        """Adds recharge to current_balance and updates balance source"""
        amount = Decimal(amount)
        self.current_balance += amount
        self.balance_source = 'recharge'
        self.has_recharged = True
        self.is_fake_display_mode = False  # Exit fake mode on recharge
        self.save(update_fields=[
            'current_balance',
            'balance_source',
            'has_recharged',
            'is_fake_display_mode'
        ])

    def add_referral_commission(self, amount):
        """Adds referral commission and updates balance source if needed"""
        amount = Decimal(amount)
        self.referral_earned_balance += amount
        self.referral_commission += amount
        
        # If no recharge done yet and no current balance, set to referral mode
        if not self.has_recharged and self.current_balance == 0:
            self.balance_source = 'referral'
            self.is_fake_display_mode = True
            self.fake_mode_started_at = timezone.now()
            
        self.save(update_fields=[
            'referral_earned_balance',
            'referral_commission',
            'balance_source',
            'is_fake_display_mode',
            'fake_mode_started_at'
        ])

    def spend_balance(self, amount):
        """Deducts from the appropriate balance source"""
        amount = Decimal(amount)
        
        if self.balance_source == 'recharge':
            if self.current_balance >= amount:
                self.current_balance -= amount
                # If balance is depleted, switch to referral if available
                if self.current_balance == 0 and self.referral_earned_balance > 0:
                    self.balance_source = 'referral'
                    self.is_fake_display_mode = True
                    self.fake_mode_started_at = timezone.now()
                self.save()
                return True
            return False
            
        elif self.balance_source == 'referral':
            if self.referral_earned_balance >= amount:
                self.referral_earned_balance -= amount
                # If referral balance is depleted, try to switch to recharge
                if self.referral_earned_balance == 0 and self.current_balance > 0:
                    self.balance_source = 'recharge'
                    self.is_fake_display_mode = False
                self.save()
                return True
            return False
        return False

    def add_product_commission(self, amount):
        """Adds product commission to the wallet"""
        amount = Decimal(amount)
        self.product_commission += amount
        self.save(update_fields=['product_commission'])

class CustomerServiceBalanceAdjustment(models.Model):
    FIELD_CHOICES = [
        ("current_balance", "Spendable Balance"),
        ("product_commission", "Product Commission"),
        ("referral_commission", "Referral Commission"),
    ]

    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cs_balance_adjustments",
    )
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="performed_cs_balance_adjustments",
    )
    field = models.CharField(max_length=32, choices=FIELD_CHOICES)
    delta = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        direction = "credit" if self.delta >= 0 else "debit"
        return (
            f"{self.get_field_display()} {direction} "
            f"{self.delta} for {self.target_user.username}"
        )


# -----------------------------
# RechargeRequest model
# -----------------------------
class RechargeRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.amount} - {self.status}"


# -----------------------------
# Voucher model
# -----------------------------
class Voucher(models.Model):
    recharge_request = models.OneToOneField(RechargeRequest, on_delete=models.CASCADE)
    file = models.FileField(upload_to="vouchers/")

    def __str__(self):
        return f"Voucher for {self.recharge_request.user.username} - {self.recharge_request.amount}"


# -----------------------------
# RechargeHistory model
# -----------------------------
class RechargeHistory(models.Model):
    STATUS_CHOICES = [
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    recharge_request = models.ForeignKey(
        RechargeRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_entries"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    voucher_file = models.FileField(upload_to="vouchers/history/", null=True, blank=True)
    action_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.amount} - {self.status} - {self.action_date}"




# -----------------------------
# BalanceRequest model
# -----------------------------
class BalanceRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - Request {self.amount} - {self.status}"

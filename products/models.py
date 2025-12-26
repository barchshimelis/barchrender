import random
import string
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_product_code():
    """Generate a code like 'BLC-24R-MMR' (LLL-DDL-LLL)."""
    part_one = ''.join(random.choices(string.ascii_uppercase, k=3))
    digits = ''.join(random.choices(string.digits, k=2))
    trailing_letter = random.choice(string.ascii_uppercase)
    part_three = ''.join(random.choices(string.ascii_uppercase, k=3))
    return f"{part_one}-{digits}{trailing_letter}-{part_three}"


def _normalize_product_code(raw_code: str) -> str:
    from .utils import format_product_code

    return format_product_code(raw_code or "")


class Product(models.Model):
    CYCLE_CHOICES = (
        (1, "Cycle 1"),
        (2, "Cycle 2"),
        (3, "Cycle 3"),
    )
    ROLE_CHOICES = (
        ("referee", "Referee"),
        ("referrer", "Referrer"),
    )

    name = models.CharField(max_length=255, default='Product')
    product_code = models.CharField(max_length=11, unique=True, blank=True)

    description = models.TextField(blank=True, default='')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    file = models.ImageField(upload_to='products/')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    cycle_number = models.PositiveSmallIntegerField(choices=CYCLE_CHOICES, default=1, db_index=True)
    role_pool = models.CharField(max_length=20, choices=ROLE_CHOICES, default="referee", db_index=True)
    sequence_in_cycle = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.product_code or 'no-code'}) - Price: {self.price}"

    def _generate_unique_code(self):
        for _ in range(10):  # try up to 10 times
            code = _normalize_product_code(generate_product_code())
            if not Product.objects.filter(product_code=code).exists():
                return code
        # fallback: append timestamp if collision (very unlikely)
        return _normalize_product_code(
            f"{generate_product_code()}{int(timezone.now().timestamp()) % 10}"
        )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            # initial save to get created_at and pk
            super().save(*args, **kwargs)
            # ensure unique product_code
            if not self.product_code:
                self.product_code = self._generate_unique_code()

            # Set name from product_code and build description
            normalized_code = _normalize_product_code(self.product_code)
            self.product_code = normalized_code
            self.name = normalized_code
            created = timezone.now()
            self.description = (
                f"Product {normalized_code} created on "
                f"{created.strftime('%Y-%m-%d %H:%M:%S')} with name '{self.name}' "
                f"and price {self.price}"
            )

            # update the fields we just set
            super().save(update_fields=['product_code', 'name', 'description'])
            return
        # for updates on existing products, just behave normally
        if self.product_code:
            self.product_code = _normalize_product_code(self.product_code)
            self.name = self.product_code
            kwargs.setdefault('update_fields', None)
            if kwargs['update_fields'] is None or 'name' not in kwargs['update_fields']:
                kwargs['update_fields'] = None
        super().save(*args, **kwargs)


class ProductCycleState(models.Model):
    active_cycle = models.PositiveSmallIntegerField(default=1, choices=Product.CYCLE_CHOICES)
    referee_completed = models.BooleanField(default=False)
    referrer_completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cycle {self.active_cycle}"


class UserProductTask(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='user_tasks')
    task_number = models.PositiveIntegerField(null=True)  # temporarily nullable
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    commissioned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Fake Display Mode fields
    fake_display_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # shown to user
    real_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # actually deducted
    is_fake_mode_task = models.BooleanField(default=False)  # track if task was in fake mode
    pricing_snapshot_daily_limit = models.PositiveIntegerField(null=True, blank=True)

    is_assigned = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(null=True, blank=True)  # Will be updated in a data migration
    round_number = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['user', 'task_number']
        unique_together = ['user', 'product', 'round_number']

    def __str__(self):
        return f"Task #{self.task_number} for {self.user} - Product {self.product.product_code} - Price: {self.price}"


class FeaturedImage(models.Model):
    title = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=500, blank=True)
    image = models.ImageField(upload_to='feature/')
    link_url = models.URLField(blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.title or f"Featured image #{self.pk}"
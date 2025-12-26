from django.db.models.signals import post_save
from django.dispatch import receiver
from products.models import UserProductTask
from .utils import calculate_product_commission
from balance.utils import update_wallet_balance

#@receiver(post_save, sender=UserProductTask)
#def handle_product_completion(sender, instance, created, **kwargs):
    # Only trigger commission once after task is completed
  ######## instance.save(update_fields=['commissioned'])

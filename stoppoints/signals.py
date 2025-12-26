from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import StopPointProgress

User = settings.AUTH_USER_MODEL

@receiver(post_save, sender=User)
def create_user_stoppoint_progress(sender, instance, created, **kwargs):
    """Create a StopPointProgress for new users."""
    if created:
        StopPointProgress.objects.create(user=instance)

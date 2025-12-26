from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.timezone import localtime
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def unread_notification_count(request):
    """Return unread notification count plus recent notification details."""
    unread_qs = Notification.objects.filter(
        recipient=request.user,
        is_read=False
    )
    count = unread_qs.count()

    recent_notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')[:10]

    notifications_payload = [
        {
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "category": notification.category,
            "target_url": notification.target_url,
            "created_at": localtime(notification.created_at).isoformat(),
            "read_at": localtime(notification.read_at).isoformat() if notification.read_at else None,
            "metadata": notification.metadata or {},
        }
        for notification in recent_notifications
    ]

    return JsonResponse({
        'count': count,
        'notifications': notifications_payload,
    })


@require_POST
@login_required
def mark_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(
        is_read=True,
        read_at=timezone.now()
    )
    return JsonResponse({'status': 'ok'})

from typing import Any, Dict, Iterable, Optional

from django.db import transaction

from accounts.models import CustomUser
from .models import Notification, AdminDashboardEvent


def _get_users_by_roles(roles: Iterable[str]) -> Iterable[CustomUser]:
    return CustomUser.objects.filter(role__in=roles, is_active=True)


def _get_superadmins() -> Iterable[CustomUser]:
    return _get_users_by_roles(["superadmin"])


def create_notification_for_users(
    *,
    recipients: Iterable[CustomUser],
    title: str,
    message: str,
    category: str,
    target_url: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    recipients = list(recipients)
    if not recipients:
        return
    with transaction.atomic():
        Notification.objects.bulk_create([
            Notification(
                recipient=user,
                title=title,
                message=message,
                category=category,
                target_url=target_url,
                metadata=metadata or {},
            )
            for user in recipients
        ])


def notify_roles(
    *,
    roles: Iterable[str],
    title: str,
    message: str,
    category: str,
    target_url: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    create_notification_for_users(
        recipients=_get_users_by_roles(roles),
        title=title,
        message=message,
        category=category,
        target_url=target_url,
        metadata=metadata,
    )


def notify_superadmins(
    title: str,
    message: str,
    category: str,
    target_url: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    notify_roles(
        roles=("superadmin",),
        title=title,
        message=message,
        category=category,
        target_url=target_url,
        metadata=metadata,
    )


def create_admin_dashboard_event(
    *,
    user: CustomUser,
    event_type: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record an admin dashboard event for bell notifications."""
    AdminDashboardEvent.objects.create(
        user=user,
        event_type=event_type,
        message=message,
        metadata=metadata or {},
    )

"""Utility helpers for staff chat between admins and the super admin."""

from __future__ import annotations

import mimetypes
from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import StaffChatMessage, StaffChatThread


class StaffChatConfigurationError(Exception):
    """Raised when staff chat cannot be configured (e.g., no super admin exists)."""


def _serialize_user(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.get_full_name() or user.get_short_name() or user.username or user.phone,
        "role": getattr(user, "role", None),
    }


def serialize_staff_message(message: StaffChatMessage) -> dict:
    attachment_data = None
    if message.attachment:
        url = message.attachment.url
        name = message.attachment.name.split("/")[-1]
        mime_type, _ = mimetypes.guess_type(url)
        mime_type = mime_type or ""
        attachment_data = {
            "url": url,
            "name": name,
            "mime_type": mime_type,
            "is_image": mime_type.startswith("image/") if mime_type else False,
            "is_audio": mime_type.startswith("audio/") if mime_type else False,
        }

    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "sender_id": message.sender_id,
        "sender_role": message.sender_role,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "attachment": attachment_data,
    }


def serialize_staff_thread(
    thread: StaffChatThread,
    *,
    include_participants: bool = True,
) -> dict:
    payload = {
        "id": thread.id,
        "admin_id": thread.admin_id,
        "superadmin_id": thread.superadmin_id,
        "admin_unread_count": thread.admin_unread_count,
        "superadmin_unread_count": thread.superadmin_unread_count,
        "last_message_preview": thread.last_message_preview,
        "last_activity": thread.last_activity.isoformat() if thread.last_activity else None,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
    }
    if include_participants:
        payload["admin"] = _serialize_user(thread.admin)
        payload["superadmin"] = _serialize_user(thread.superadmin)
    return payload


def serialize_messages(messages: Iterable[StaffChatMessage]) -> list[dict]:
    return [serialize_staff_message(msg) for msg in messages]


def get_global_superadmin():
    User = get_user_model()
    return User.objects.filter(role="superadmin", is_active=True).order_by("id").first()


def ensure_thread_for_admin(admin_user) -> StaffChatThread:
    if getattr(admin_user, "role", None) != "admin":
        raise ValueError("Thread can only be created for admin users.")

    superadmin = get_global_superadmin()
    if not superadmin:
        raise StaffChatConfigurationError("No active super admin account is configured.")

    thread, _ = StaffChatThread.objects.select_related("admin", "superadmin").get_or_create(
        admin=admin_user,
        superadmin=superadmin,
    )
    return thread


def add_staff_message(
    thread: StaffChatThread,
    sender,
    content: str,
    *,
    attachment_file=None,
    attachment_name: Optional[str] = None,
) -> tuple[StaffChatMessage, StaffChatThread]:
    text = (content or "").strip()
    if not text and attachment_file is None:
        raise ValueError("Message content cannot be empty.")

    if attachment_name:
        preview_source = attachment_name
    elif text:
        preview_source = text
    else:
        preview_source = "Attachment"

    preview = (preview_source or "").strip()[:255]

    with transaction.atomic():
        message_kwargs = {
            "thread": thread,
            "sender": sender,
            "sender_role": getattr(sender, "role", "unknown"),
            "content": text,
        }
        if attachment_file is not None:
            message_kwargs["attachment"] = attachment_file

        message = StaffChatMessage.objects.create(**message_kwargs)

        updates = {
            "last_message_preview": preview,
            "last_activity": timezone.now(),
        }
        if getattr(sender, "role", None) == "admin":
            updates["superadmin_unread_count"] = F("superadmin_unread_count") + 1
        else:
            updates["admin_unread_count"] = F("admin_unread_count") + 1

        StaffChatThread.objects.filter(pk=thread.pk).update(**updates)

    thread.refresh_from_db()
    message.refresh_from_db()
    return message, thread


def mark_thread_read(thread: StaffChatThread, role: str) -> StaffChatThread:
    updates: dict[str, int] = {}
    if role == "admin":
        updates["admin_unread_count"] = 0
    elif role == "superadmin":
        updates["superadmin_unread_count"] = 0

    if updates:
        StaffChatThread.objects.filter(pk=thread.pk).update(**updates)
        thread.refresh_from_db(fields=list(updates.keys()))
    return thread


def get_thread_for_user(thread_id: int, user) -> Optional[StaffChatThread]:
    try:
        thread = StaffChatThread.objects.select_related("admin", "superadmin").get(pk=thread_id)
    except StaffChatThread.DoesNotExist:
        return None

    if user.id not in (thread.admin_id, thread.superadmin_id):
        return None
    return thread


def get_thread_messages(thread: StaffChatThread, *, limit: int = 50) -> list[dict]:
    qs = thread.messages.order_by("-created_at")[:limit]
    ordered = list(reversed(list(qs)))
    return serialize_messages(ordered)

"""Utility helpers for persistent user ↔ customer service chat."""

from __future__ import annotations

import mimetypes
from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import UserSupportMessage, UserSupportThread


def _serialize_user(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.get_full_name() or user.get_short_name() or user.username or user.phone,
        "role": getattr(user, "role", None),
    }


def serialize_support_message(message: UserSupportMessage) -> dict:
    attachment_data = None
    if message.attachment:
        url = message.attachment.url
        name = (message.attachment.name or "").split("/")[-1]
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


def serialize_support_thread(
    thread: UserSupportThread,
    *,
    include_participants: bool = True,
) -> dict:
    payload = {
        "id": thread.id,
        "user_id": thread.user_id,
        "assigned_agent_id": thread.assigned_agent_id,
        "user_unread_count": thread.user_unread_count,
        "agent_unread_count": thread.agent_unread_count,
        "last_message_preview": thread.last_message_preview,
        "last_activity": thread.last_activity.isoformat() if thread.last_activity else None,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
    }
    if include_participants:
        payload["user"] = _serialize_user(thread.user)
        payload["assigned_agent"] = _serialize_user(thread.assigned_agent) if thread.assigned_agent else None
    return payload


def serialize_support_messages(messages: Iterable[UserSupportMessage]) -> list[dict]:
    return [serialize_support_message(msg) for msg in messages]


def get_default_customer_service_agent():
    User = get_user_model()
    return (
        User.objects.filter(role="customerservice", is_active=True)
        .order_by("id")
        .first()
    )


def ensure_thread_for_user(user, *, auto_assign: bool = True) -> UserSupportThread:
    if getattr(user, "role", None) != "user":
        raise ValueError("Persistent support threads can only be opened for regular users.")

    defaults = {}
    if auto_assign:
        agent = get_default_customer_service_agent()
        if agent:
            defaults["assigned_agent"] = agent

    thread, _ = UserSupportThread.objects.select_related("user", "assigned_agent").get_or_create(
        user=user,
        defaults=defaults,
    )
    return thread


def add_support_message(
    thread: UserSupportThread,
    sender,
    content: str,
    *,
    attachment_file=None,
    attachment_name: Optional[str] = None,
) -> tuple[UserSupportMessage, UserSupportThread]:
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

        message = UserSupportMessage.objects.create(**message_kwargs)

        updates = {
            "last_message_preview": preview,
            "last_activity": timezone.now(),
        }
        if sender.id == thread.user_id:
            updates["agent_unread_count"] = F("agent_unread_count") + 1
        else:
            updates["user_unread_count"] = F("user_unread_count") + 1

        UserSupportThread.objects.filter(pk=thread.pk).update(**updates)

    thread.refresh_from_db()
    message.refresh_from_db()
    return message, thread


def mark_support_thread_read(thread: UserSupportThread, actor_role: str) -> UserSupportThread:
    updates: dict[str, int] = {}
    if actor_role == "user":
        updates["user_unread_count"] = 0
    else:
        updates["agent_unread_count"] = 0

    if updates:
        UserSupportThread.objects.filter(pk=thread.pk).update(**updates)
        thread.refresh_from_db(fields=list(updates.keys()))
    return thread


def get_support_thread_for_participant(thread_id: int, user) -> Optional[UserSupportThread]:
    try:
        thread = UserSupportThread.objects.select_related("user", "assigned_agent").get(pk=thread_id)
    except UserSupportThread.DoesNotExist:
        return None

    if user.id == thread.user_id:
        return thread

    role = getattr(user, "role", None)
    if role in {"customerservice", "superadmin"}:
        return thread

    if thread.assigned_agent_id and user.id == thread.assigned_agent_id:
        return thread

    return None


def get_support_thread_messages(thread: UserSupportThread, *, limit: int = 50) -> list[dict]:
    qs = thread.messages.order_by("-created_at")[:limit]
    ordered = list(reversed(list(qs)))
    return serialize_support_messages(ordered)


def recompute_support_thread_snapshot(thread: UserSupportThread) -> UserSupportThread:
    """Refresh last message preview and activity after destructive actions (e.g., delete)."""

    latest = thread.messages.order_by("-created_at").first()
    if latest:
        if latest.attachment_id:
            preview_source = latest.attachment.name.split("/")[-1] if latest.attachment.name else "Attachment"
        else:
            preview_source = latest.content or ""

        thread.last_message_preview = (preview_source or "").strip()[:255]
        thread.last_activity = latest.created_at or timezone.now()
    else:
        thread.last_message_preview = ""
        thread.last_activity = timezone.now()

    thread.save(update_fields=["last_message_preview", "last_activity"])
    return thread

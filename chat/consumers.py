"""Channels WebSocket consumer for simplechat.

Handles both guests and a single CS agent on the same WS path.
All data lives in the in‑memory session_store.
"""
import base64
import mimetypes
from datetime import datetime

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.conf import settings

from .session_store import (
    ensure_session,
    add_message,
    mark_read,
    register_channel,
    unregister_channel,
    list_sessions,
    schedule_idle_purge,
)
from .services import (
    add_staff_message,
    get_thread_for_user,
    get_thread_messages,
    mark_thread_read,
    serialize_staff_message,
    serialize_staff_thread,
)

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf", "text/plain",
    "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

class SimpleChatConsumer(AsyncJsonWebsocketConsumer):
    """Unified consumer for guest and CS roles."""

    async def connect(self):
        # Identify the thread slug from URL
        self.thread_slug = self.scope["url_route"]["kwargs"]["slug"]
        self.group_name = f"chat_{self.thread_slug}"

        # Determine role:
        # - Guest: slug must be present in their Django session
        # - CS: user is authenticated (you can adapt to your CS user model)
        session = self.scope["session"]
        if session.get("chat_thread_slug") == self.thread_slug:
            self.role = "guest"
        else:
            # For now we assume any authenticated user is CS; replace with your CS check
            user = self.scope.get("user")
            if user and user.is_authenticated:
                self.role = "cs"
            else:
                await self.close()
                return

        # Join the group and register channel in the in‑memory store
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        register_channel(self.thread_slug, self.channel_name, self.role)

        # Accept the connection
        await self.accept()

        # Send any buffered messages (newest first)
        rec = ensure_session(self.thread_slug)
        messages = list(rec["messages"])
        messages.reverse()  # show oldest first in UI
        await self.send_json({
            "event": "bootstrap",
            "messages": messages,
        })

    async def disconnect(self, close_code):
        # Clean up channel registration
        unregister_channel(self.thread_slug, self.channel_name, self.role)

        # If nobody is left, schedule idle purge (2 minutes)
        rec = ensure_session(self.thread_slug)
        if not rec["guest_channels"] and not rec["cs_channels"]:
            schedule_idle_purge(self.thread_slug)

        # Leave the group
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        if action == "message":
            await self.handle_message(content.get("message", ""))
        elif action == "file":
            await self.handle_file_upload(content)
        elif action == "read":
            mark_read(self.thread_slug)
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "stream.event", "event": "read"},
            )
        elif action == "typing":
            await self.handle_typing(bool(content.get("is_typing", False)))
        elif action == "leave":
            await self.close()
        else:
            # Unknown action – ignore or send error
            pass

    async def handle_message(self, text: str):
        if not text:
            return
        add_message(self.thread_slug, self.role, text)
        rec = ensure_session(self.thread_slug)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "stream.event",
                "event": "message",
                "message": rec["messages"][0],  # newest message
            },
        )

    async def handle_file_upload(self, payload):
        """Accept base64 file, validate size/type, save, and broadcast."""
        file_data = payload.get("file_data")
        file_name = payload.get("file_name")
        mime_type = payload.get("mime_type")

        if not (file_data and file_name and mime_type):
            await self.send_json({"event": "error", "detail": "Invalid file payload"})
            return

        # Decode and size check
        try:
            decoded = base64.b64decode(file_data)
        except Exception:
            await self.send_json({"event": "error", "detail": "Corrupt file data"})
            return

        if len(decoded) > MAX_FILE_SIZE:
            await self.send_json({"event": "error", "detail": "File exceeds 2 MB"})
            return

        if mime_type not in ALLOWED_MIME_TYPES:
            await self.send_json({"event": "error", "detail": "File type not allowed"})
            return

        # Save to MEDIA_ROOT/simplechat/<slug>/<timestamp>_<filename>
        from django.utils.timezone import now
        timestamp = now().strftime("%Y%m%d%H%M%S")
        safe_name = f"{timestamp}_{file_name}"
        rel_path = f"simplechat/{self.thread_slug}/{safe_name}"
        full_path = settings.MEDIA_ROOT / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with full_path.open("wb") as f:
            f.write(decoded)

        # For images, send as base64 data URL to avoid media serving issues
        if mime_type.startswith('image/'):
            data_url = f"data:{mime_type};base64,{file_data}"
            attachment = {
                "url": data_url,
                "name": file_name,
                "mime_type": mime_type,
            }
        else:
            # For non-images, use media URL
            attachment = {
                "url": settings.MEDIA_URL + rel_path,
                "name": file_name,
                "mime_type": mime_type,
            }
        add_message(self.thread_slug, self.role, "", attachment=attachment)
        rec = ensure_session(self.thread_slug)
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "stream.event",
                "event": "message",
                "message": rec["messages"][0],
            },
        )

    async def handle_typing(self, is_typing: bool):
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "stream.event",
                "event": "typing",
                "is_typing": is_typing,
                "role": self.role,
            },
        )

    async def stream_event(self, event):
        """Helper used by channel_layer.group_send."""
        await self.send_json({
            "event": event["event"],
            **{k: v for k, v in event.items() if k != "type" and k != "event"},
        })

    async def send_json(self, payload):
        await super().send_json(payload)


class StaffChatConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for admin ↔ superadmin staff chat."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close()
            return

        try:
            self.thread_id = int(self.scope["url_route"]["kwargs"]["thread_id"])
        except (KeyError, ValueError, TypeError):
            await self.close()
            return

        thread = await database_sync_to_async(get_thread_for_user)(self.thread_id, user)
        if not thread:
            await self.close()
            return

        self.user = user
        self.thread = thread
        self.role = "admin" if user.id == thread.admin_id else "superadmin"
        self.group_name = f"staff_chat_{self.thread_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        messages = await database_sync_to_async(get_thread_messages)(self.thread)
        await self.send_json({
            "event": "bootstrap",
            "thread": serialize_staff_thread(self.thread),
            "messages": messages,
        })

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(getattr(self, "group_name", ""), self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")

        if action == "message":
            await self._handle_message(content.get("message", ""))
        elif action == "read":
            await self._handle_read()
        else:
            await self.send_json({"event": "error", "detail": "Unknown action."})

    async def _handle_message(self, text: str):
        message_text = (text or "").strip()
        if not message_text:
            await self.send_json({"event": "error", "detail": "Message cannot be empty."})
            return

        message, thread = await database_sync_to_async(add_staff_message)(self.thread, self.user, message_text)
        self.thread = thread

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "staff.event",
                "event": "message",
                "message": serialize_staff_message(message),
                "thread": serialize_staff_thread(thread, include_participants=False),
            },
        )

    async def _handle_read(self):
        thread = await database_sync_to_async(mark_thread_read)(self.thread, self.role)
        self.thread = thread

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "staff.event",
                "event": "read",
                "role": self.role,
                "thread": serialize_staff_thread(thread, include_participants=False),
            },
        )

    async def staff_event(self, event):
        await self.send_json({
            "event": event.get("event"),
            **{k: v for k, v in event.items() if k not in {"type", "event"}},
        })
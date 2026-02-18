import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse, HttpResponseForbidden, Http404, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .session_store import make_slug, ensure_session, list_sessions
from .services import (
    StaffChatConfigurationError,
    add_staff_message,
    ensure_thread_for_admin,
    get_thread_for_user,
    get_thread_messages,
    mark_thread_read,
    rebuild_thread_snapshot,
    serialize_staff_message,
    serialize_staff_thread,
)
from .services_support import (
    add_support_message,
    ensure_thread_for_user as ensure_support_thread_for_user,
    get_support_thread_for_participant,
    get_support_thread_messages,
    mark_support_thread_read,
    recompute_support_thread_snapshot,
    serialize_support_message,
    serialize_support_thread,
)
from .models import StaffChatThread, StaffChatMessage, UserSupportThread, UserSupportMessage


User = get_user_model()


def guest_new(request):
    """Create a slug, store it in the visitor’s session, and redirect to the chat room."""
    session = request.session
    # Reuse existing slug if visitor refreshes
    slug = session.get("chat_thread_slug")
    if not slug:
        slug = make_slug()
        session["chat_thread_slug"] = slug
        session.save()
    ensure_session(slug)  # create in‑memory record
    return redirect("chat:guest_room", slug=slug)


def guest_room(request, slug):
    """Render the guest chat page."""
    # Optional: verify the slug matches the session for security
    if request.session.get("chat_thread_slug") != slug:
        return redirect("chat:guest_new")
    return render(request, "chat/guest_chat.html", {"slug": slug})


def cs_panel(request):
    """Render the CS dashboard (list + conversation pane)."""
    # You can add permission checks here (e.g., staff only)
    return render(request, "chat/cs_panel.html")


def cs_thread_list(request):
    """Return JSON of active sessions for the CS dashboard."""
    # You can add permission checks here
    sessions = list_sessions()
    return JsonResponse({"threads": sessions})


def _require_role(user, role: str) -> bool:
    return getattr(user, "role", None) == role


def _require_cs_agent(user) -> bool:
    return getattr(user, "role", None) in {"customerservice", "superadmin"}


def _messages_limit(request) -> int:
    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return max(1, min(200, limit))


@login_required
def user_support_portal(request):
    """Render the unified customer service chat workspace for users and CS agents."""

    role = getattr(request.user, "role", None)
    if role == "user":
        thread = ensure_support_thread_for_user(request.user)
        thread_id = thread.id
    elif role in {"customerservice", "superadmin"}:
        thread = None
        thread_id = None
    else:
        return HttpResponseForbidden("Support chat is only available to regular users and customer service staff.")

    context = {
        "support_role": role,
        "thread_id": thread_id,
        "bootstrap_url": reverse("chat:user_support_bootstrap"),
        "thread_messages_url": reverse("chat:user_support_thread_messages", args=[thread_id]) if thread_id else "",
        "send_url": reverse("chat:user_support_send_message", args=[thread_id]) if thread_id else "",
        "read_url": reverse("chat:user_support_mark_read", args=[thread_id]) if thread_id else "",
        "cs_thread_list_url": reverse("chat:cs_support_thread_list") if role in {"customerservice", "superadmin"} else "",
        "ws_path": f"/ws/support/{thread_id}/" if thread_id else "",
        "thread_messages_template": reverse("chat:user_support_thread_messages", args=[0]),
        "send_template": reverse("chat:user_support_send_message", args=[0]),
        "read_template": reverse("chat:user_support_mark_read", args=[0]),
        "upload_template": reverse("chat:user_support_upload_attachment", args=[0]),
        "delete_template": reverse("chat:user_support_delete_message", args=[0, 0]),
        "ws_base": "/ws/support/",
    }
    return render(request, "chat/user_support_portal.html", context)


@login_required
@require_GET
def admin_staff_chat_bootstrap(request):
    """Ensure the admin↔superadmin thread exists and return initial payload."""

    user = request.user
    if not _require_role(user, "admin"):
        return HttpResponseForbidden("Admin role required")

    try:
        thread = ensure_thread_for_admin(user)
    except StaffChatConfigurationError as exc:
        return JsonResponse({"error": str(exc)}, status=409)

    messages = get_thread_messages(thread, limit=_messages_limit(request))
    return JsonResponse({
        "thread": serialize_staff_thread(thread),
        "messages": messages,
    })


@login_required
@require_POST
def user_support_delete_message(request, thread_id: int, message_id: int):
    """Allow customer service agents to delete any message in a user support chat."""

    if getattr(request.user, "role", None) != "customerservice":
        return HttpResponseForbidden("Customer service role required.")

    thread = get_support_thread_for_participant(thread_id, request.user)
    if not thread:
        raise Http404("Support thread not found.")

    message = get_object_or_404(UserSupportMessage, pk=message_id, thread=thread)
    deleted_message_id = message.id
    message.delete()

    thread = recompute_support_thread_snapshot(thread)

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_support_{thread.id}",
        {
            "type": "support.event",
            "event": "delete",
            "message_id": deleted_message_id,
            "thread": serialize_support_thread(thread, include_participants=False),
        },
    )

    return JsonResponse({"deleted_message_id": deleted_message_id})


@login_required
@require_GET
def superadmin_staff_thread_list(request):
    """Return all admin threads for the authenticated superadmin."""

    user = request.user
    if not _require_role(user, "superadmin"):
        return HttpResponseForbidden("Superadmin role required")

    threads = (
        StaffChatThread.objects
        .filter(superadmin=user)
        .select_related("admin", "superadmin")
        .order_by("-last_activity")
    )
    data = [serialize_staff_thread(thread) for thread in threads]
    total_unread = sum(thread.superadmin_unread_count for thread in threads)
    return JsonResponse({
        "threads": data,
        "total_unread": total_unread,
    })


@login_required
@require_POST
def superadmin_staff_create_thread(request):
    """Allow the superadmin to proactively open a thread with an admin."""

    user = request.user
    if not _require_role(user, "superadmin"):
        return HttpResponseForbidden("Superadmin role required")

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    admin_id = payload.get("admin_id")
    if not admin_id:
        return JsonResponse({"error": "admin_id is required"}, status=400)

    try:
        admin_user = User.objects.get(pk=admin_id, role="admin", is_active=True)
    except User.DoesNotExist:
        raise Http404("Admin user not found")

    thread = ensure_thread_for_admin(admin_user)
    messages = get_thread_messages(thread, limit=_messages_limit(request))

    return JsonResponse({
        "thread": serialize_staff_thread(thread),
        "messages": messages,
    })


@login_required
@require_GET
def staff_chat_thread_messages(request, thread_id: int):
    """Return messages for a thread the current user participates in."""

    thread = get_thread_for_user(thread_id, request.user)
    if not thread:
        raise Http404("Thread not found")

    messages = get_thread_messages(thread, limit=_messages_limit(request))
    return JsonResponse({
        "thread": serialize_staff_thread(thread),
        "messages": messages,
    })


@login_required
@require_POST
def staff_chat_mark_read(request, thread_id: int):
    """Reset unread counters for the acting participant."""

    thread = get_thread_for_user(thread_id, request.user)
    if not thread:
        raise Http404("Thread not found")

    role = "admin" if request.user.id == thread.admin_id else "superadmin"
    thread = mark_thread_read(thread, role)

    return JsonResponse({
        "thread": serialize_staff_thread(thread),
        "role": role,
    })


@login_required
@require_POST
def staff_chat_upload_attachment(request, thread_id: int):
    """Handle image/audio uploads (≤5MB) for staff chat messages."""

    thread = get_thread_for_user(thread_id, request.user)
    if not thread:
        raise Http404("Thread not found")

    upload: "UploadedFile" | None = request.FILES.get("attachment")
    if not upload:
        return HttpResponseBadRequest("Missing attachment")

    max_bytes = 5 * 1024 * 1024
    if upload.size > max_bytes:
        return JsonResponse({"error": "File exceeds 5 MB limit."}, status=400)

    allowed_prefixes = ("image/", "audio/")
    content_type = (upload.content_type or "").lower()
    if not content_type.startswith(allowed_prefixes):
        return JsonResponse({"error": "Only image or audio files are allowed."}, status=400)

    message_text = request.POST.get("message", "")

    message, thread = add_staff_message(
        thread,
        request.user,
        message_text,
        attachment_file=upload,
        attachment_name=upload.name,
    )

    channel_layer = get_channel_layer()
    payload = {
        "type": "staff.event",
        "event": "message",
        "message": serialize_staff_message(message),
        "thread": serialize_staff_thread(thread, include_participants=False),
    }
    async_to_sync(channel_layer.group_send)(f"staff_chat_{thread.id}", payload)

    return JsonResponse({
        "message": serialize_staff_message(message),
        "thread": serialize_staff_thread(thread),
    })


@login_required
@require_GET
def staff_chat_unread_summary(request):
    """Return badge totals for the active user."""

    user = request.user
    role = getattr(user, "role", None)

    if role == "admin":
        try:
            thread = StaffChatThread.objects.select_related("superadmin").get(admin=user)
        except StaffChatThread.DoesNotExist:
            return JsonResponse({"total_unread": 0, "thread": None})

        return JsonResponse({
            "total_unread": thread.admin_unread_count,
            "thread": serialize_staff_thread(thread),
        })

    if role == "superadmin":
        threads = (
            StaffChatThread.objects
            .filter(superadmin=user)
            .select_related("admin", "superadmin")
        )
        total = threads.aggregate(total=Sum("superadmin_unread_count"))
        return JsonResponse({
            "total_unread": total["total"] or 0,
            "threads": [serialize_staff_thread(thread) for thread in threads],
        })

    return JsonResponse({"total_unread": 0})


@login_required
@require_POST
def superadmin_staff_delete_message(request, thread_id: int, message_id: int):
    """Allow the superadmin to delete any message in their staff chat threads."""

    user = request.user
    if not _require_role(user, "superadmin"):
        return HttpResponseForbidden("Superadmin role required")

    thread = get_thread_for_user(thread_id, user)
    if not thread or thread.superadmin_id != user.id:
        raise Http404("Thread not found")

    message = get_object_or_404(StaffChatMessage, pk=message_id, thread=thread)
    deleted_message_id = message.id
    message.delete()

    thread = rebuild_thread_snapshot(thread)

    channel_layer = get_channel_layer()
    payload = {
        "type": "staff.event",
        "event": "delete",
        "message_id": deleted_message_id,
        "thread": serialize_staff_thread(thread, include_participants=False),
    }
    async_to_sync(channel_layer.group_send)(f"staff_chat_{thread.id}", payload)

    return JsonResponse({"deleted_message_id": deleted_message_id})


# ---------------------------------------------------------------------
# Persistent user customer service chat APIs
# ---------------------------------------------------------------------


@login_required
@require_GET
def user_support_bootstrap(request):
    """Ensure the logged-in user has a support thread and return initial payload."""

    if not _require_role(request.user, "user"):
        return HttpResponseForbidden("Regular user account required.")

    thread = ensure_support_thread_for_user(request.user)
    messages = get_support_thread_messages(thread, limit=_messages_limit(request))

    return JsonResponse({
        "thread": serialize_support_thread(thread),
        "messages": messages,
    })


@login_required
@require_GET
def user_support_thread_messages(request, thread_id: int):
    """Return message history for any participant (user or CS agent)."""

    thread = get_support_thread_for_participant(thread_id, request.user)
    if not thread:
        raise Http404("Support thread not found.")

    messages = get_support_thread_messages(thread, limit=_messages_limit(request))
    return JsonResponse({
        "thread": serialize_support_thread(thread),
        "messages": messages,
    })


@login_required
@require_POST
def user_support_send_message(request, thread_id: int):
    """Allow a participant (user or CS agent) to send a message."""

    thread = get_support_thread_for_participant(thread_id, request.user)
    if not thread:
        raise Http404("Support thread not found.")

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    text = (payload.get("message") or "").strip()
    if not text:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    message, thread = add_support_message(thread, request.user, text)

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_support_{thread.id}",
        {
            "type": "support.event",
            "event": "message",
            "message": serialize_support_message(message),
            "thread": serialize_support_thread(thread, include_participants=False),
        },
    )

    return JsonResponse({
        "message": serialize_support_message(message),
        "thread": serialize_support_thread(thread),
    })


@login_required
@require_POST
def user_support_upload_attachment(request, thread_id: int):
    """Allow participants to upload media files (≤3 MB) to the support thread."""

    thread = get_support_thread_for_participant(thread_id, request.user)
    if not thread:
        raise Http404("Support thread not found.")

    upload = request.FILES.get("attachment")
    if not upload:
        return HttpResponseBadRequest("Missing attachment")

    max_bytes = 3 * 1024 * 1024
    if upload.size > max_bytes:
        return JsonResponse({"error": "File exceeds 3 MB limit."}, status=400)

    allowed_prefixes = ("image/", "video/", "audio/")
    content_type = (upload.content_type or "").lower()
    if content_type and not content_type.startswith(allowed_prefixes):
        return JsonResponse({"error": "Only image, video, or audio files are allowed."}, status=400)

    message, thread = add_support_message(
        thread,
        request.user,
        "",
        attachment_file=upload,
        attachment_name=upload.name,
    )

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_support_{thread.id}",
        {
            "type": "support.event",
            "event": "message",
            "message": serialize_support_message(message),
            "thread": serialize_support_thread(thread, include_participants=False),
        },
    )

    return JsonResponse({
        "message": serialize_support_message(message),
        "thread": serialize_support_thread(thread),
    })


@login_required
@require_POST
def user_support_mark_read(request, thread_id: int):
    """Reset unread counters for whichever participant is making the call."""

    thread = get_support_thread_for_participant(thread_id, request.user)
    if not thread:
        raise Http404("Support thread not found.")

    role = "user" if request.user.id == thread.user_id else "agent"
    thread = mark_support_thread_read(thread, role)

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_support_{thread.id}",
        {
            "type": "support.event",
            "event": "read",
            "role": role,
            "thread": serialize_support_thread(thread, include_participants=False),
        },
    )

    return JsonResponse({
        "thread": serialize_support_thread(thread),
        "role": role,
    })


@login_required
@require_GET
def cs_support_thread_list(request):
    """List user support threads for CS agents / superadmin."""

    if not _require_cs_agent(request.user):
        return HttpResponseForbidden("Customer service role required.")

    threads = (
        UserSupportThread.objects
        .select_related("user", "assigned_agent")
        .order_by("-last_activity")
    )

    data = [serialize_support_thread(thread) for thread in threads]
    total_unread = sum(thread.agent_unread_count for thread in threads)
    return JsonResponse({
        "threads": data,
        "total_unread": total_unread,
    })

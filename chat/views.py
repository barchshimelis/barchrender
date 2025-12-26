import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse, HttpResponseForbidden, Http404, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt

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
    serialize_staff_message,
    serialize_staff_thread,
)
from .models import StaffChatThread


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


def _messages_limit(request) -> int:
    try:
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    return max(1, min(200, limit))


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

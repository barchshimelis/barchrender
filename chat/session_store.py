"""In‑memory store for simplechat.

Each session (identified by a slug) tracks:
- messages (deque, capped)
- unread count for CS
- sets of connected channel names for guests and CS agents
- timestamps for creation and last activity

All data lives in RAM; it disappears on server restart.
"""
import uuid
from collections import deque
from datetime import datetime, timedelta
from threading import Timer

# Global dict: slug -> SessionRecord
_sessions = {}

# Helper to generate a slug
def make_slug() -> str:
    return f"guest-{uuid.uuid4().hex[:12]}"

# Session record shape
def _make_record() -> dict:
    return {
        "messages": deque(maxlen=50),           # newest first, capped
        "unread_for_cs": 0,
        "guest_channels": set(),
        "cs_channels": set(),
        "created_at": datetime.utcnow(),
        "last_activity": datetime.utcnow(),
    }

# Ensure a session exists; returns the record
def ensure_session(slug: str) -> dict:
    if slug not in _sessions:
        _sessions[slug] = _make_record()
    _sessions[slug]["last_activity"] = datetime.utcnow()
    return _sessions[slug]

# Add a message dict to a session and bump unread if from guest
def add_message(slug: str, sender_role: str, content: str, attachment: dict | None = None) -> None:
    rec = ensure_session(slug)
    msg = {
        "sender_role": sender_role,
        "content": content,
        "attachment": attachment,
        "created_at": datetime.utcnow().isoformat(),
    }
    rec["messages"].appendleft(msg)  # newest at left
    rec["last_activity"] = datetime.utcnow()
    if sender_role == "guest":
        rec["unread_for_cs"] += 1

# Mark CS as having read the thread
def mark_read(slug: str) -> None:
    if slug in _sessions:
        _sessions[slug]["unread_for_cs"] = 0
        _sessions[slug]["last_activity"] = datetime.utcnow()

# Register a channel name for a given role
def register_channel(slug: str, channel_name: str, role: str) -> None:
    rec = ensure_session(slug)
    if role == "guest":
        rec["guest_channels"].add(channel_name)
    elif role == "cs":
        rec["cs_channels"].add(channel_name)

# Unregister a channel name
def unregister_channel(slug: str, channel_name: str, role: str) -> None:
    if slug not in _sessions:
        return
    rec = _sessions[slug]
    if role == "guest":
        rec["guest_channels"].discard(channel_name)
    elif role == "cs":
        rec["cs_channels"].discard(channel_name)
    rec["last_activity"] = datetime.utcnow()

# Return a list of active sessions for CS dashboard
def list_sessions() -> list[dict]:
    out = []
    for slug, rec in _sessions.items():
        if rec["guest_channels"] or rec["cs_channels"]:
            out.append({
                "slug": slug,
                "unread_for_cs": rec["unread_for_cs"],
                "last_activity": rec["last_activity"].isoformat(),
                "created_at": rec["created_at"].isoformat(),
            })
    # newest activity first
    out.sort(key=lambda s: s["last_activity"], reverse=True)
    return out

# Delete a session entirely (used by idle purge)
def delete_session(slug: str) -> None:
    _sessions.pop(slug, None)

# Idle purge: remove sessions with no channels for 2 minutes
def schedule_idle_purge(slug: str, delay_seconds: int = 120) -> None:
    def _purge():
        if slug not in _sessions:
            return
        rec = _sessions[slug]
        if not rec["guest_channels"] and not rec["cs_channels"]:
            delete_session(slug)
    Timer(delay_seconds, _purge).start()
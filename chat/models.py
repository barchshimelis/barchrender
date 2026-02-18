from django.conf import settings
from django.db import models
from django.utils import timezone


class StaffChatThread(models.Model):
    """Private channel between a single admin and the super admin."""

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_chat_threads",
        help_text="Admin participant of the thread.",
    )
    superadmin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_chat_threads_as_superadmin",
        help_text="Super admin participant of the thread.",
    )
    admin_unread_count = models.PositiveIntegerField(default=0)
    superadmin_unread_count = models.PositiveIntegerField(default=0)
    last_message_preview = models.CharField(max_length=255, blank=True)
    last_activity = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("admin", "superadmin")
        ordering = ("-last_activity",)

    def __str__(self):
        return f"Staff chat: {self.admin_id} ↔ {self.superadmin_id}"


class StaffChatMessage(models.Model):
    """Message exchanged inside a staff chat thread."""

    thread = models.ForeignKey(StaffChatThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_chat_messages")
    sender_role = models.CharField(max_length=20)
    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to="staff_chat/attachments/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Message {self.pk} in thread {self.thread_id}"


class UserSupportThread(models.Model):
    """
    Persistent 1:1 channel between a logged-in user and the customer service team.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_thread",
        help_text="Regular user who owns this thread.",
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_support_threads",
        help_text="Optional customer service agent overseeing the thread.",
    )
    user_unread_count = models.PositiveIntegerField(default=0)
    agent_unread_count = models.PositiveIntegerField(default=0)
    last_message_preview = models.CharField(max_length=255, blank=True)
    last_activity = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-last_activity",)

    def __str__(self):
        return f"Support chat for user {self.user_id}"


class UserSupportMessage(models.Model):
    """Message stored inside a persistent user ↔ customer service thread."""

    thread = models.ForeignKey(UserSupportThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_messages")
    sender_role = models.CharField(max_length=20)
    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to="support_chat/attachments/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Support message {self.pk} in thread {self.thread_id}"

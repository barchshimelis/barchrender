from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffChatThread",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("admin_unread_count", models.PositiveIntegerField(default=0)),
                ("superadmin_unread_count", models.PositiveIntegerField(default=0)),
                ("last_message_preview", models.CharField(blank=True, max_length=255)),
                ("last_activity", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "admin",
                    models.ForeignKey(
                        help_text="Admin participant of the thread.",
                        on_delete=models.deletion.CASCADE,
                        related_name="staff_chat_threads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "superadmin",
                    models.ForeignKey(
                        help_text="Super admin participant of the thread.",
                        on_delete=models.deletion.CASCADE,
                        related_name="staff_chat_threads_as_superadmin",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-last_activity",),
                "unique_together": {("admin", "superadmin")},
            },
        ),
        migrations.CreateModel(
            name="StaffChatMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sender_role", models.CharField(max_length=20)),
                ("content", models.TextField(blank=True)),
                ("attachment", models.FileField(blank=True, null=True, upload_to="staff_chat/attachments/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sender",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="staff_chat_messages",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "thread",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="messages",
                        to="simplechat.staffchatthread",
                    ),
                ),
            ],
            options={"ordering": ("created_at",)},
        ),
    ]

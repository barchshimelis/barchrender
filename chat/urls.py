"""HTTP URL configuration for simplechat.

- guest_new: creates a slug, stores it in the visitor’s session, redirects.
- guest_room: renders the guest chat page.
- cs_panel: renders CS dashboard.
- cs_thread_list: JSON list of active sessions for the dashboard.
"""
from django.urls import path
from . import views

app_name = "chat"

urlpatterns = [
    path("guest/new/", views.guest_new, name="guest_new"),
    path("guest/<slug:slug>/", views.guest_room, name="guest_room"),
    path("cs/", views.cs_panel, name="cs_panel"),
    path("cs/threads/", views.cs_thread_list, name="cs_thread_list"),
    path("staff/admin/bootstrap/", views.admin_staff_chat_bootstrap, name="admin_staff_chat_bootstrap"),
    path("staff/superadmin/threads/", views.superadmin_staff_thread_list, name="superadmin_staff_thread_list"),
    path("staff/superadmin/threads/create/", views.superadmin_staff_create_thread, name="superadmin_staff_create_thread"),
    path("staff/threads/<int:thread_id>/messages/", views.staff_chat_thread_messages, name="staff_chat_thread_messages"),
    path("staff/threads/<int:thread_id>/read/", views.staff_chat_mark_read, name="staff_chat_mark_read"),
    path("staff/threads/<int:thread_id>/upload/", views.staff_chat_upload_attachment, name="staff_chat_upload_attachment"),
    path("staff/unread/", views.staff_chat_unread_summary, name="staff_chat_unread_summary"),
]
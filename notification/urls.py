# In notification/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('api/notifications/unread-count/', views.unread_notification_count, name='unread_notification_count'),
    path('api/notifications/mark-read/', views.mark_notifications_read, name='mark_notifications_read'),
]
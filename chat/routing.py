"""WebSocket URL routing for simplechat.

Maps ws://host/ws/chat/<slug>/ to SimpleChatConsumer.
"""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/chat/(?P<slug>[\w-]+)/$", consumers.SimpleChatConsumer.as_asgi()),
    re_path(r"ws/staff/(?P<thread_id>\d+)/$", consumers.StaffChatConsumer.as_asgi()),
]
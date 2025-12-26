"""ASGI entrypoint for AmazonProject.
Supports traditional HTTP via Django and WebSocket via Django Channels.
"""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AmazonProject.settings")

import django

django.setup()

import chat.routing as chat_routing

django_http_app = get_asgi_application()

if settings.DEBUG:
    django_http_app = ASGIStaticFilesHandler(django_http_app)

# Main ASGI application
application = ProtocolTypeRouter({
    "http": django_http_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(chat_routing.websocket_urlpatterns)
    ),
})
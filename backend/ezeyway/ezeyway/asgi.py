import os

# Initialize Django first before importing any Django modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ezeyway.settings')

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from accounts.websocket_auth import TokenAuthMiddlewareStack
from accounts.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": TokenAuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})
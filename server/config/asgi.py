# config/asgi.py

import os
from django.core.asgi import get_asgi_application

# 必須在導入其他模塊之前設置環境變量
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# 先初始化 Django ASGI application
django_asgi_app = get_asgi_application()

# 然後導入 channels 相關模塊
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from light_control.routing import websocket_urlpatterns

# 配置 ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
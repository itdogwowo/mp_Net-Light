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

# 🔥 新增:導入並啟動設備發現服務
from slave_controller.device_discovery import discovery_service

print("[ASGI] 正在啟動設備發現服務...")
discovery_service.start()
print("[ASGI] 設備發現服務已啟動")

# 配置 ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
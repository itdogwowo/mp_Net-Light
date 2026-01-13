# config/asgi.py (完整修正版)
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# 🔥 只導入一次,使用別名
from light_control.routing import websocket_urlpatterns as light_ws
from slave_controller.routing import websocket_urlpatterns as slave_ws

# 🔥 合併路由
all_websocket_patterns = light_ws + slave_ws

# 🔥 啟動設備發現服務
from slave_controller.device_discovery import discovery_service
print("[ASGI] 正在啟動設備發現服務...")
discovery_service.start()
print("[ASGI] 設備發現服務已啟動")

# 🔥 打印所有路由
print("\n所有 WebSocket 路由:")
for pattern in all_websocket_patterns:
    print(f"  - {pattern.pattern}")
print()

# 🔥 配置 ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(all_websocket_patterns)  # 🔥 使用合併後的路由
    ),
})
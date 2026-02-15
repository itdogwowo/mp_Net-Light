<<<<<<< HEAD
# config/asgi.py (完整修正版)
=======
# config/asgi.py - 確認配置正確
>>>>>>> main
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# 🔥 只導入一次,使用別名
from api.routing import websocket_urlpatterns as api_ws
from apps.routing import websocket_urlpatterns as apps_ws
from core.routing import websocket_urlpatterns as core_ws
from webUI.routing import websocket_urlpatterns as appTimer_ws
from appTimer.routing import websocket_urlpatterns as webUI_ws

# 🔥 合併路由
all_websocket_patterns = api_ws + apps_ws + core_ws + webUI_ws + appTimer_ws

# 🔥 打印所有路由
print("\n所有 WebSocket 路由:")
for pattern in all_websocket_patterns:
    print(f"  - {pattern.pattern}")

# 🔥 配置 ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(all_websocket_patterns)  # 🔥 使用合併後的路由
    ),
})

print("✅ ASGI 配置完成")
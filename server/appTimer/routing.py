# light_control/routing.py - 確認路由配置
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # 設備控制 WebSocket
    re_path(r'ws/appTimer/(?P<device_id>\w+)/$', consumers.AppTimerConsumer.as_asgi()),
    
]

print("WebSocket 路由已加載:")
for pattern in websocket_urlpatterns:
    print(f"  - {pattern.pattern}")
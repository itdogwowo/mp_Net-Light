# light_control/routing.py - 確認路由配置
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # 設備控制 WebSocket
    re_path(r'ws/light/device/(?P<device_id>\w+)/$', consumers.LightControlConsumer.as_asgi()),
    
    # 播放控制 WebSocket（播放器模式）
    re_path(r'ws/light/playback/$', consumers.LightControlConsumer.as_asgi()),
    
    # 監察 WebSocket（監察模式）
    re_path(r'ws/light/monitor/$', consumers.LightControlConsumer.as_asgi()),
]

print("WebSocket 路由已加載:")
for pattern in websocket_urlpatterns:
    print(f"  - {pattern.pattern}")
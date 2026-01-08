# light_control/routing.py
from django.urls import re_path, path
from . import consumers

websocket_urlpatterns = [
    # 設備控制 WebSocket
    re_path(r'ws/light/device/(?P<device_id>\w+)/$', consumers.LightControlConsumer.as_asgi()),
    
    # 播放控制 WebSocket（使用特殊設備ID "playback"）
    re_path(r'ws/light/playback/$', consumers.LightControlConsumer.as_asgi()),
]
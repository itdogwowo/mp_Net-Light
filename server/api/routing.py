# api/routing.py - 確認路由配置
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # 使用 re_path 確保精確匹配，加上 $ 符號結尾
    re_path(r'^ws/slave/(?P<slave_id>.+)$', consumers.APIConsumer.as_asgi()),
    re_path(r"ws/api/?$", consumers.APIConsumer.as_asgi()),
]

print("WebSocket 路由已加載:")
for pattern in websocket_urlpatterns:
    print(f"  - {pattern.pattern}")
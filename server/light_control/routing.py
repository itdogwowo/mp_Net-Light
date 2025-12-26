# light_control/routing.py

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/light/(?P<device_id>\w+)/$', consumers.LightControlConsumer.as_asgi()),
]
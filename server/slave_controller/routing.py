from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/slave/(?P<slave_id>.+)$', consumers.SlaveConsumer.as_asgi()),
]
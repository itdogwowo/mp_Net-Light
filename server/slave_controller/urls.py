# slave_controller/urls.py
from django.urls import path
from . import views

app_name = 'slave_controller'

urlpatterns = [
    path('', views.device_list_page, name='device_list'),
    path('api/devices/', views.api_device_list, name='api_device_list'),
    path('api/discover/', views.api_discover, name='api_discover'),              # 🔥 新增
    path('api/device/connect/', views.api_device_connect, name='api_device_connect'),  # 🔥 新增
    path('api/file/upload/', views.api_file_upload, name='api_file_upload'),
    path('api/file/download/', views.api_file_download, name='api_file_download'),

    # 🔥 新增: STATUS 指令 API
    path('api/slave/status/get/', views.api_slave_get_status, name='api_slave_get_status'),
    path('api/slave/status/update/', views.api_slave_update_status, name='api_slave_update_status'),

    path('api/stream/start/', views.api_stream_start, name='api_stream_start'),
    path('api/stream/stop/', views.api_stream_stop, name='api_stream_stop'),

    path('api/schema/download/', views.api_schema_download, name='api_schema_download'),
    path('api/schema/list/<str:slave_id>/', views.api_schema_list, name='api_schema_list'),
    
]
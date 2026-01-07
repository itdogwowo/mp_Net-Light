# light_control/urls.py

from django.urls import path
from . import views
from . import api_views

app_name = 'light_control'

urlpatterns = [
    # path('', views.index, name='index'),  # 修正:應該用 name 參數,而不是 view
    # path('dashboard/', views.dashboard, name='dashboard'),

    path("", views.dashboard, name="dashboard"),
    path("mapping/", views.mapping_editor, name="mapping"),

    path("api/pxld/info/", api_views.pxld_info, name="pxld_info"),
    path("api/pxld/slaves/", api_views.pxld_slaves, name="pxld_slaves"),
    path("api/pxld/slave_frame_rgbw", api_views.pxld_slave_frame_rgbw, name="pxld_slave_frame_rgbw"),

    path("api/config/slaves/get/", api_views.cfg_slaves_get, name="cfg_slaves_get"),
    path("api/config/slaves/set/", api_views.cfg_slaves_set, name="cfg_slaves_set"),
    path("api/config/layout/get/", api_views.cfg_layout_get, name="cfg_layout_get"),
    path("api/config/layout/set/", api_views.cfg_layout_set, name="cfg_layout_set"),

    path("api/mapping/get/", api_views.mapping_get, name="mapping_get"),
    path("api/mapping/set/", api_views.mapping_set, name="mapping_set"),
]
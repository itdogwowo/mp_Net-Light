# api/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'devices', views.DeviceViewSet, basename='device')
router.register(r'effects', views.LightEffectViewSet, basename='effect')
router.register(r'logs', views.CommandLogViewSet, basename='log')

urlpatterns = [
    path('', include(router.urls)),
]
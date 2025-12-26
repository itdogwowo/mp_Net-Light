# light_control/views.py

from django.shortcuts import render
from django.http import JsonResponse
from .models import Device, LightEffect

def index(request):
    """主頁"""
    context = {
        'title': 'mp_Net-Light 控制中心',
        'total_devices': Device.objects.count(),
        'online_devices': Device.objects.filter(status='online').count(),
        'total_effects': LightEffect.objects.filter(is_active=True).count(),
    }
    return render(request, 'light_control/index.html', context)

def dashboard(request):
    """儀表板"""
    devices = Device.objects.all()
    effects = LightEffect.objects.filter(is_active=True)
    
    context = {
        'title': '設備控制台',
        'devices': devices,
        'effects': effects,
    }
    return render(request, 'light_control/dashboard.html', context)
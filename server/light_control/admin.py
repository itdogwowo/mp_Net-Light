# light_control/admin.py

from django.contrib import admin
from .models import Device, LightEffect, CommandLog

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'name', 'status', 'current_effect', 'brightness', 'last_seen']
    list_filter = ['status', 'current_effect']
    search_fields = ['device_id', 'name', 'ip_address']
    readonly_fields = ['created_at', 'updated_at', 'last_seen']

@admin.register(LightEffect)
class LightEffectAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'display_name']

@admin.register(CommandLog)
class CommandLogAdmin(admin.ModelAdmin):
    list_display = ['device', 'command', 'success', 'created_at']
    list_filter = ['success', 'command', 'created_at']
    search_fields = ['device__name', 'command']
    readonly_fields = ['created_at']
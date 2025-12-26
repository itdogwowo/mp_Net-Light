# api/serializers.py

from rest_framework import serializers
from light_control.models import Device, LightEffect, CommandLog

class DeviceSerializer(serializers.ModelSerializer):
    """設備序列化器"""
    
    class Meta:
        model = Device
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'last_seen']


class LightEffectSerializer(serializers.ModelSerializer):
    """燈效序列化器"""
    
    class Meta:
        model = LightEffect
        fields = '__all__'
        read_only_fields = ['created_at']


class CommandLogSerializer(serializers.ModelSerializer):
    """命令日誌序列化器"""
    
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = CommandLog
        fields = '__all__'
        read_only_fields = ['created_at']
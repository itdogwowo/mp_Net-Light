# api/views.py

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from light_control.models import Device, LightEffect, CommandLog
from .serializers import DeviceSerializer, LightEffectSerializer, CommandLogSerializer


class DeviceViewSet(viewsets.ModelViewSet):
    """設備管理 API"""
    
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    lookup_field = 'device_id'
    
    @action(detail=True, methods=['post'])
    def send_command(self, request, device_id=None):
        """發送命令到設備"""
        device = self.get_object()
        command = request.data.get('command')
        parameters = request.data.get('parameters', {})
        
        if not command:
            return Response(
                {'error': 'Command is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 通過 WebSocket 發送命令
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'device_{device_id}',
            {
                'type': 'light_command',
                'command': command,
                'parameters': parameters
            }
        )
        
        return Response({
            'status': 'success',
            'message': f'Command "{command}" sent to device {device_id}',
            'device': DeviceSerializer(device).data
        })
    
    @action(detail=False, methods=['get'])
    def online(self, request):
        """獲取在線設備"""
        online_devices = self.queryset.filter(status='online')
        serializer = self.get_serializer(online_devices, many=True)
        return Response(serializer.data)


class LightEffectViewSet(viewsets.ModelViewSet):
    """燈效管理 API"""
    
    queryset = LightEffect.objects.filter(is_active=True)
    serializer_class = LightEffectSerializer


class CommandLogViewSet(viewsets.ReadOnlyModelViewSet):
    """命令日誌 API (只讀)"""
    
    queryset = CommandLog.objects.all()
    serializer_class = CommandLogSerializer
    
    def get_queryset(self):
        """支持按設備過濾"""
        queryset = super().get_queryset()
        device_id = self.request.query_params.get('device_id')
        if device_id:
            queryset = queryset.filter(device__device_id=device_id)
        return queryset
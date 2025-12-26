# light_control/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from datetime import datetime

class LightControlConsumer(AsyncWebsocketConsumer):
    """燈效控制 WebSocket Consumer"""
    
    async def connect(self):
        """客戶端連接"""
        # 從 URL 獲取設備 ID
        self.device_id = self.scope['url_route']['kwargs'].get('device_id', 'unknown')
        self.room_group_name = f'device_{self.device_id}'
        
        # 加入房間組
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # 接受連接
        await self.accept()
        
        # 更新設備狀態為在線
        await self.update_device_status('online')
        
        # 發送歡迎消息
        await self.send(text_data=json.dumps({
            'type': 'connection',
            'message': 'Connected to mp_Net-Light Server',
            'device_id': self.device_id,
            'timestamp': datetime.now().isoformat()
        }))
        
        print(f"[WebSocket] Device {self.device_id} connected")
    
    async def disconnect(self, close_code):
        """客戶端斷開"""
        # 更新設備狀態為離線
        await self.update_device_status('offline')
        
        # 離開房間組
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        print(f"[WebSocket] Device {self.device_id} disconnected with code {close_code}")
    
    async def receive(self, text_data):
        """接收客戶端消息"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            print(f"[WebSocket] Received from {self.device_id}: {data}")
            
            # 處理不同類型的消息
            if message_type == 'heartbeat':
                # 心跳包
                await self.update_device_status('online')
                await self.send(text_data=json.dumps({
                    'type': 'heartbeat_ack',
                    'timestamp': datetime.now().isoformat()
                }))
            
            elif message_type == 'status':
                # 狀態更新
                await self.handle_status_update(data)
            
            elif message_type == 'response':
                # 命令響應
                await self.handle_command_response(data)
            
            else:
                # 未知消息類型
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                }))
        
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
    
    async def light_command(self, event):
        """發送燈效命令到設備"""
        await self.send(text_data=json.dumps({
            'type': 'command',
            'command': event['command'],
            'parameters': event.get('parameters', {}),
            'timestamp': datetime.now().isoformat()
        }))
    
    async def handle_status_update(self, data):
        """處理設備狀態更新"""
        # 這裡可以更新數據庫中的設備狀態
        status = data.get('status', {})
        await self.update_device_info(status)
        
        await self.send(text_data=json.dumps({
            'type': 'status_ack',
            'message': 'Status updated'
        }))
    
    async def handle_command_response(self, data):
        """處理命令響應"""
        # 記錄命令執行結果
        await self.log_command(data)
        
        print(f"[WebSocket] Command response from {self.device_id}: {data}")
    
    @database_sync_to_async
    def update_device_status(self, status):
        """更新設備狀態"""
        from .models import Device
        from django.utils import timezone
        
        device, created = Device.objects.get_or_create(
            device_id=self.device_id,
            defaults={'name': f'Device {self.device_id}'}
        )
        device.status = status
        device.last_seen = timezone.now()
        device.save()
    
    @database_sync_to_async
    def update_device_info(self, status):
        """更新設備詳細信息"""
        from .models import Device
        
        try:
            device = Device.objects.get(device_id=self.device_id)
            if 'current_effect' in status:
                device.current_effect = status['current_effect']
            if 'brightness' in status:
                device.brightness = status['brightness']
            device.save()
        except Device.DoesNotExist:
            pass
    
    @database_sync_to_async
    def log_command(self, data):
        """記錄命令執行"""
        from .models import Device, CommandLog
        
        try:
            device = Device.objects.get(device_id=self.device_id)
            CommandLog.objects.create(
                device=device,
                command=data.get('command', 'unknown'),
                parameters=data.get('parameters', {}),
                success=data.get('success', False),
                response=data.get('message', '')
            )
        except Device.DoesNotExist:
            pass
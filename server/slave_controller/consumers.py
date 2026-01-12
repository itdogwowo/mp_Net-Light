# slave_controller/consumers.py (完整版)
import asyncio
import struct
from channels.generic.websocket import AsyncWebsocketConsumer
from datetime import datetime

class SlaveConsumer(AsyncWebsocketConsumer):
    """Slave WebSocket Consumer - 處理 CMD 二進位協議"""
    
    async def connect(self):
        """Slave 連接"""
        self.slave_id = self.scope['url_route']['kwargs'].get('slave_id')
        self.room_group_name = f'slave_{self.slave_id}'
        
        print("=" * 50)
        print(f"[SlaveWS] Slave {self.slave_id} 嘗試連接")
        
        # 加入房間組
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # 接受連接
        await self.accept()
        
        print(f"[SlaveWS] ✅ Slave {self.slave_id} WebSocket 已連接")
        print("=" * 50)
    
    async def disconnect(self, close_code):
        """Slave 斷開"""
        print(f"[SlaveWS] Slave {self.slave_id} WebSocket 已斷開 (code: {close_code})")
        
        # 離開房間組
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data=None, bytes_data=None):
        """接收消息"""
        if bytes_data:
            await self._handle_cmd_packet(bytes_data)
        elif text_data:
            print(f"[SlaveWS] 收到文本: {text_data[:100]}")
    
    async def _handle_cmd_packet(self, packet):
        """處理 CMD 封包"""
        if len(packet) < 11:
            return
        
        sof = packet[0:2]
        if sof != b'NL':
            return
        
        cmd = struct.unpack('<H', packet[5:7])[0]
        length = struct.unpack('<H', packet[7:9])[0]
        
        print(f"[SlaveWS] 📥 收到 CMD: 0x{cmd:04X}, LEN: {length}")
        
        # 根據 CMD 處理
        if cmd == 0x1102:  # STATUS_RSP
            await self._handle_status_rsp(packet[9:9+length])
        elif cmd == 0x1104:  # STATUS_UPDATE_ACK
            await self._handle_status_update_ack(packet[9:9+length])
    
    async def _handle_status_rsp(self, payload):
        """處理 STATUS_RSP"""
        try:
            str_len = struct.unpack('<H', payload[0:2])[0]
            status_json = payload[2:2+str_len].decode('utf-8')
            
            print(f"[SlaveWS] 📊 STATUS_RSP: {status_json[:100]}...")
            
            # 發送到前端
            await self.send(text_data=status_json)
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 STATUS_RSP 錯誤: {e}")
    
    async def _handle_status_update_ack(self, payload):
        """處理 STATUS_UPDATE_ACK"""
        try:
            success = payload[0]
            str_len = struct.unpack('<H', payload[1:3])[0]
            message = payload[3:3+str_len].decode('utf-8')
            
            print(f"[SlaveWS] ✅ STATUS_UPDATE_ACK: success={success}, msg={message}")
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理錯誤: {e}")
    
    async def send_cmd(self, event):
        """從 channel layer 接收並發送 CMD 封包"""
        packet = event.get('packet')
        if packet:
            await self.send(bytes_data=packet)
            print(f"[SlaveWS] 📤 已發送 CMD: {len(packet)} bytes") 
# slave_controller/consumers.py (修復版 + 調試日誌)
import asyncio, json
import struct
from channels.generic.websocket import AsyncWebsocketConsumer
from datetime import datetime
from .device_discovery import discovery_service

class AdminConsumer(AsyncWebsocketConsumer):
    """管理後台 WebSocket Consumer - 接收設備狀態更新"""
    
    async def connect(self):
        """管理員連接"""
        # 加入管理員房間
        await self.channel_layer.group_add(
            'admin_room',
            self.channel_name
        )
        
        await self.accept()
        print("[AdminWS] ✅ 管理員 WebSocket 已連接")
        
        # 🔥 連接後立即發送當前設備列表
        from .device_discovery import discovery_service
        devices = discovery_service.get_devices()
        
        await self.send(text_data=json.dumps({
            "type": "device_list",
            "devices": devices
        }))
    
    async def disconnect(self, close_code):
        """管理員斷開"""
        await self.channel_layer.group_discard(
            'admin_room',
            self.channel_name
        )
        print(f"[AdminWS] 管理員已斷開 (code: {close_code})")
    
    async def device_status_update(self, event):
        """🔥 接收設備狀態更新並推送到前端"""
        await self.send(text_data=json.dumps({
            "type": "device_status",
            "slave_id": event.get("slave_id"),
            "status": event.get("status"),
            "ws_connected": event.get("ws_connected"),
            "timestamp": event.get("timestamp")
        }))



class SlaveConsumer(AsyncWebsocketConsumer):
    """Slave WebSocket Consumer - 處理 CMD 二進位協議 (修復版)"""
    
    async def connect(self):
        """Slave 連接"""
        self.slave_id = self.scope['url_route']['kwargs'].get('slave_id')
        self.room_group_name = f'slave_{self.slave_id}'
        
        from .protocol.proto import StreamParser
        self.parser = StreamParser(max_len=65536)
        
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.channel_layer.group_add('all_slaves', self.channel_name)
        await self.accept()
        
        discovery_service.update_device_status(
            self.slave_id, "online", ws_connected=True
        )
        
        print(f"[SlaveWS] ✅ {self.slave_id} 已連接")
        
        # 🔥 通知管理員
        await self.channel_layer.group_send(
            'admin_room',
            {
                'type': 'device_status_update',
                'slave_id': self.slave_id,
                'status': 'online',
                'ws_connected': True,
                'timestamp': datetime.now().isoformat()
            }
        )
    
    async def disconnect(self, close_code):
        """Slave 斷開"""
        discovery_service.update_device_status(
            self.slave_id, "offline", ws_connected=False
        )
        
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        await self.channel_layer.group_discard('all_slaves', self.channel_name)
        
        print(f"[SlaveWS] ❌ {self.slave_id} 已斷開")
        
        # 🔥 通知管理員
        await self.channel_layer.group_send(
            'admin_room',
            {
                'type': 'device_status_update',
                'slave_id': self.slave_id,
                'status': 'offline',
                'ws_connected': False,
                'timestamp': datetime.now().isoformat()
            }
        )
    
    
    async def receive(self, text_data=None, bytes_data=None):
        """🔥 接收消息 (修復版 + 調試日誌)"""
        if bytes_data:
            print(f"[SlaveWS-DEBUG] 📩 收到原始數據: {len(bytes_data)} bytes")  # 👈 這行必須存在!
            print(f"[SlaveWS-DEBUG] 前16字節: {bytes_data[:16].hex()}")
            await self._handle_cmd_packets(bytes_data)
        elif text_data:
            print(f"[SlaveWS] 收到文本: {text_data[:100]}")
    
    async def _handle_cmd_packets(self, data):
        """🔥 處理 CMD 封包 (修復版 + 調試日誌)"""
        # 餵給 StreamParser
        self.parser.feed(data)
        
        print(f"[SlaveWS-DEBUG] 🔍 開始解析封包...")
        
        # 🔥 修復:正確使用生成器
        packet_count = 0
        try:
            for ver, addr, cmd, payload in self.parser.pop():
                packet_count += 1
                
                print(f"[SlaveWS-DEBUG] 📦 解析封包 #{packet_count}:")
                print(f"[SlaveWS-DEBUG]   VER: {ver}")
                print(f"[SlaveWS-DEBUG]   ADDR: 0x{addr:04X}")
                print(f"[SlaveWS-DEBUG]   CMD: 0x{cmd:04X}")
                print(f"[SlaveWS-DEBUG]   Payload: {len(payload)} bytes")
                
                # 根據 CMD 分發處理
                await self._dispatch_cmd(cmd, payload)
        
        except Exception as e:
            print(f"[SlaveWS] ❌ 解析封包錯誤: {e}")
            import traceback
            traceback.print_exc()
        
        if packet_count == 0:
            print(f"[SlaveWS-DEBUG] ⚠️ StreamParser 沒有解析出任何封包")
            print(f"[SlaveWS-DEBUG] Buffer 狀態: {len(self.parser.buf)} bytes")
    
    async def _dispatch_cmd(self, cmd, payload):
        """🔥 CMD 分發處理 (詳細日誌版)"""
        print(f"[SlaveWS] 📥 收到 CMD: 0x{cmd:04X}, LEN: {len(payload)}")
        
        # 根據 CMD 處理
        if cmd == 0x1102:  # STATUS_RSP
            print(f"[SlaveWS] 處理 STATUS_RSP")
            await self._handle_status_rsp(payload)
        
        elif cmd == 0x1104:  # STATUS_UPDATE_ACK
            print(f"[SlaveWS] 處理 STATUS_UPDATE_ACK")
            await self._handle_status_update_ack(payload)
        
        elif cmd == 0x1201:  # HEARTBEAT (如果已實現)
            print(f"[SlaveWS] 處理 HEARTBEAT")
            await self._handle_heartbeat(payload)
        
        else:
            print(f"[SlaveWS] ⚠️ 未知 CMD: 0x{cmd:04X}")
    
    async def _handle_status_rsp(self, payload):
        """處理 STATUS_RSP"""
        try:
            # 解析 str_u16len
            str_len = struct.unpack('<H', payload[0:2])[0]
            status_json = payload[2:2+str_len].decode('utf-8')
            
            print(f"[SlaveWS] 📊 STATUS_RSP:")
            print(f"[SlaveWS]   JSON 長度: {str_len} bytes")
            print(f"[SlaveWS]   內容預覽: {status_json[:100]}...")
            
            # 發送到前端
            await self.send(text_data=status_json)
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 STATUS_RSP 錯誤: {e}")
            import traceback
            traceback.print_exc()
    
    async def _handle_status_update_ack(self, payload):
        """處理 STATUS_UPDATE_ACK"""
        try:
            success = payload[0]
            str_len = struct.unpack('<H', payload[1:3])[0]
            message = payload[3:3+str_len].decode('utf-8')
            
            print(f"[SlaveWS] ✅ STATUS_UPDATE_ACK:")
            print(f"[SlaveWS]   success: {success}")
            print(f"[SlaveWS]   message: {message}")
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 STATUS_UPDATE_ACK 錯誤: {e}")
    
    async def _handle_heartbeat(self, payload):
        """🔥 處理心跳 (詳細版)"""
        try:
            # 解析 payload
            str_len = struct.unpack('<H', payload[0:2])[0]
            slave_id = payload[2:2+str_len].decode('utf-8')
            
            offset = 2 + str_len
            uptime_ms = struct.unpack('<I', payload[offset:offset+4])[0]
            mem_free = struct.unpack('<I', payload[offset+4:offset+8])[0]
            ws_connected = payload[offset+8]
            
            print(f"[SlaveWS] 💓 心跳:")
            print(f"[SlaveWS]   Slave ID: {slave_id}")
            print(f"[SlaveWS]   Uptime: {uptime_ms} ms")
            print(f"[SlaveWS]   RAM Free: {mem_free} bytes")
            
            # 更新心跳
            discovery_service.update_heartbeat(slave_id, {
                "uptime_ms": uptime_ms,
                "mem_free": mem_free,
                "ws_connected": bool(ws_connected)
            })
            
            # 回應 HEARTBEAT_ACK
            import time
            ack_payload = struct.pack('<IB', int(time.time()), 1)
            ack_packet = self._pack_cmd(0x1202, ack_payload)
            
            await self.send(bytes_data=ack_packet)
            print(f"[SlaveWS] 💓 已回應 HEARTBEAT_ACK")
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理心跳錯誤: {e}")
            import traceback
            traceback.print_exc()
    
    def _pack_cmd(self, cmd, payload):
        """簡易封包打包"""
        sof = b'NL'
        ver = bytes([3])
        addr = struct.pack('<H', 0)
        cmd_bytes = struct.pack('<H', cmd)
        length = struct.pack('<H', len(payload))
        
        # 🔥 計算真實 CRC16
        from .protocol.proto import crc16_ccitt
        crc_data = ver + addr + cmd_bytes + length + payload
        crc = crc16_ccitt(crc_data)
        crc_bytes = struct.pack('<H', crc)
        
        return sof + ver + addr + cmd_bytes + length + payload + crc_bytes
    
    async def send_cmd(self, event):
        """從 channel layer 接收並發送 CMD 封包"""
        packet = event.get('packet')
        if packet:
            print(f"[SlaveWS] 📤 發送封包詳情:")
            print(f"  長度: {len(packet)} bytes")
            print(f"  前16字節: {packet[:min(16, len(packet))].hex()}")
            
            await self.send(bytes_data=packet)
            print(f"[SlaveWS] 📤 已發送 CMD: {len(packet)} bytes")
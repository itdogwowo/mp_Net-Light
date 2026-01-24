# server/api/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from core.bus_manager import bus_manager


class APIConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.slave_id = self.scope['url_route']['kwargs'].get('slave_id')
        if self.slave_id:
            self.peer_type = "SLAVE"
            await self.accept()
            # 🚀 註冊 self 讓 BusManager 以後找得到這個 Socket
            bus_manager.active_slaves[self.slave_id] = self 
            bus_manager.notify_ui_update()
        else:
            self.peer_type = "UI"
            await self.accept()
            bus_manager.ui_clients[self.channel_name] = self

    async def receive(self, text_data=None, bytes_data=None):
        if self.peer_type == "SLAVE" and bytes_data:
            # 使用 ProtocolManager 解析二進位包
            from core.protocol import proto_mgr
            from core.bus_manager import bus_manager
            
            # 這裡假設你的 StreamParser 已經在 NetBus 裡跑了
            # 如果是直接從 Consumer 收到 bytes_data，我們簡單解析它：
            # (這部分視你的 StreamParser 實作而定，通常建議 feed 進 parser)
            
            # 預期解析出 CMD 0x1201
            # 一旦收到，我們就觸發一次 UI 更新
            bus_manager.notify_ui_update()
            
            # 回傳 ACK (0x1202)
            ack_pkt = proto_mgr.pack(0x1202, {"server_time": int(time.time()), "success": 1})
            await self.send(bytes_data=ack_pkt)

    async def disconnect(self, close_code):
        if hasattr(self, 'peer_type'):
            if self.peer_type == "SLAVE":
                bus_manager.unregister_slave(self.slave_id)
            else:
                bus_manager.unregister_ui(self.channel_name)
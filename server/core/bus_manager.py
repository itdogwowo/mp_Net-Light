# server/core/bus_manager.py
import time
import asyncio
import json
import socket
import threading
from .protocol import proto_mgr

class BusManager:
    def __init__(self):
        self.active_slaves = {}  
        self.ui_clients = {}     
        self.auto_scan_enabled = True
        self.scan_interval = 20
        self._bg_thread = None
        self.running = True

    def send_cmd_to_slave(self, slave_id, cmd_hex_or_int, payload_dict):
        """
        這是整個系統的靈魂：透過 WebSocket 下發 NL3 協議包
        """
        if slave_id not in self.active_slaves:
            print(f"❌ Slave {slave_id} not in pool.")
            return

        # 1. 封裝 NL3 二進位包
        pkt = proto_mgr.pack(cmd_hex_or_int, payload_dict)
        
        # 2. 獲取該 Slave 的 WebSocket 連線實例
        consumer = self.active_slaves[slave_id]
        
        # 3. 執行非同步發送
        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            consumer.send(bytes_data=pkt), # 🚀 關鍵：使用 bytes_data 發送二進位
            loop
        )
        print(f"📤 Sent CMD {cmd_hex_or_int} to {slave_id}")

    def start_background_tasks(self):
        threading.Thread(target=self._keep_alive_loop, daemon=True).start()

    def _keep_alive_loop(self):
        while True:
            # 每 10 秒戳一次所有 Slave
            for sid in list(self.active_slaves.keys()):
                # 發送 0x1201 心跳包
                self.send_cmd_to_slave(sid, 0x1201, {
                    "slave_id": "SERVER", "uptime_ms": 0, "mem_free": 0, "ws_connected": 1
                })
            time.sleep(10)

    def send_heartbeat_to_slaves(self):
        """向所有 Slave 發送心跳 (CMD 0x1201)"""
        if not self.active_slaves: return
        
        # 準備一個心跳包
        # 假設你的 schema/heartbeat.json 裡有 0x1201 (HEARTBEAT)
        try:
            hb_pkt = proto_mgr.pack(0x1201, {"timestamp": int(time.time())})
            
            # 直接通過 Consumer 發送
            loop = asyncio.get_event_loop()
            for sid, info in list(self.active_slaves.items()):
                asyncio.run_coroutine_threadsafe(info["consumer"].send(bytes_data=hb_pkt), loop)
        except Exception as e:
            print(f"Heartbeat error: {e}")

    def _scan_loop(self):
        """每隔 20 秒發送一次廣播 (如果 enabled)"""
        while True:
            if self.auto_scan_enabled:
                self.broadcast_discovery()
            time.sleep(self.scan_interval)

    def broadcast_discovery(self):
        """發送協議定義的 DISCOVERY 指令"""
        try:
            # 獲取本機 IP
            s_temp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s_temp.connect(("8.8.8.8", 80))
            local_ip = s_temp.getsockname()[0]
            s_temp.close()
            
            # 重要：Slave 會根據這個 ws_url 拼接 ID 後連回來
            payload = {
                "server_ip": local_ip, 
                "ws_url": f"ws://{local_ip}:8000/ws/slave" 
            }
            pkt = proto_mgr.pack(0x1001, payload)
            
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(pkt, ('255.255.255.255', 9000))
            s.close()
            # 同時也透過 Log 發送同步給 UI 看到
            self.send_ui_log(f"📡 Broadcast Sent: {local_ip}, scanning (20s interval)")
            print("📡 Discovery Broadcast dispatched manually.")
        except Exception as e:
            print(f"❌ Broadcast Error: {e}")

    def handle_slave_packet(self, slave_id, cmd, args):
        """
        處理來自任何 Slave 的協議包 (解碼後的 args)
        """
        if cmd == 0x1201: # HEARTBEAT
            # 1. 更新 UI 上的實時監控數據 (RAM, Uptime 等)
            # self.update_slave_health_info(slave_id, args)
            
            # 2. 立即回覆 ACK (0x1202)
            ack_payload = {
                "server_time": int(time.time()),
                "success": 1
            }
            
            # 透過該 Slave 的 WebSocket 回傳
            hub = self.get_hub(slave_id)
            if hub:
                # 直接調用 proto_mgr 打包並寫入
                pkt = proto_mgr.pack(0x1202, ack_payload)
                hub.bus.write(pkt)

    def send_ui_log(self, message, level="warning"):
        """推播日誌到 UI 終端"""
        self._dispatch_to_ui({"type": "log", "message": message, "level": level})

    def register_slave(self, slave_id, consumer):
        self.active_slaves[slave_id] = {
            "consumer": consumer,
            "ip": consumer.scope['client'][0],
            "connected_at": time.time()
        }
        self.send_ui_log(f"✨ Slave {slave_id} connected from {self.active_slaves[slave_id]['ip']}", "success")
        self.notify_ui_update()

    def unregister_slave(self, slave_id):
        if slave_id in self.active_slaves:
            del self.active_slaves[slave_id]
            self.send_ui_log(f"💔 Slave {slave_id} disconnected", "error")
            self.notify_ui_update()

    def register_ui(self, channel_name, consumer):
        self.ui_clients[channel_name] = consumer
        self.notify_ui_update()

    def unregister_ui(self, channel_name):
        if channel_name in self.ui_clients:
            del self.ui_clients[channel_name]

    def set_auto_scan(self, enabled):
        self.auto_scan_enabled = enabled
        self.send_ui_log(f"Auto-scan set to: {enabled}", "info")

    def notify_ui_update(self):
        current_fleet = []
        now = time.time()
        for sid, info in self.active_slaves.items():
            current_fleet.append({
                "slave_id": sid,
                "ip": info["ip"],
                "uptime": int(now - info["connected_at"]),
                "status": "CONNECTED"
            })
        self._dispatch_to_ui({"type": "slave_list", "data": current_fleet})

    def _dispatch_to_ui(self, data):
        """內部統一推播 UI 邏輯"""
        msg = json.dumps(data)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for channel_name, ui_consumer in list(self.ui_clients.items()):
            asyncio.run_coroutine_threadsafe(ui_consumer.send(msg), loop)

bus_manager = BusManager()
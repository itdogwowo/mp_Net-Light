# server/core/discovery.py
import time
import socket
import threading
from core.protocol import proto_mgr
from lib.proto import StreamParser

class SlaveDiscoveryService:
    def __init__(self):
        self.found_slaves = {}  # {ip: {"info": info, "last_seen": timestamp, "auto_reconnect": True}}
        self.running = False
        self.reconnect_interval = 20  # 容易修改的重連頻率 (秒)
        self.on_update_callback = None # 通知 WebSocket 

    def set_auto_reconnect(self, ip, enabled: bool):
        if ip in self.found_slaves:
            self.found_slaves[ip]["auto_reconnect"] = enabled

    def _run_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', 9000))
        sock.settimeout(1.0)
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                parser = StreamParser()
                parser.feed(data)
                for ver, p_addr, cmd, payload in parser.pop():
                    if cmd == 0x1001:
                        name, args = proto_mgr.unpack(cmd, payload)
                        ip = addr[0]
                        is_new = ip not in self.found_slaves
                        
                        self.found_slaves[ip] = {
                            "ip": ip,
                            "ws_url": args.get("ws_url"),
                            "last_seen": time.time(),
                            "auto_reconnect": self.found_slaves.get(ip, {}).get("auto_reconnect", True),
                            "status": "online"
                        }
                        if self.on_update_callback:
                            self.on_update_callback("discovery", self.found_slaves[ip])
            except socket.timeout: continue

    def _run_monitor(self):
        """定期檢查斷線與觸發重連"""
        while self.running:
            now = time.time()
            for ip, slave in list(self.found_slaves.items()):
                # 如果超過 5 秒沒收到廣播，標記為離線
                if now - slave["last_seen"] > 5 and slave["status"] == "online":
                    slave["status"] = "offline"
                    if self.on_update_callback:
                        self.on_update_callback("offline", slave)
                
                # 如果離線且開啟了自動重連，且到達重連間隔
                if slave["status"] == "offline" and slave["auto_reconnect"]:
                    if now - slave["last_seen"] > self.reconnect_interval:
                        # 這裡發送一個特殊的信號給 UI，或者嘗試主動 Probe
                        if self.on_update_callback:
                            self.on_update_callback("reconnecting", slave)
            time.sleep(1)

    def start(self):
        self.running = True
        threading.Thread(target=self._run_listener, daemon=True).start()
        threading.Thread(target=self._run_monitor, daemon=True).start()

discovery_service = SlaveDiscoveryService()

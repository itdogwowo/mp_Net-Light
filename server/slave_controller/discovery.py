import socket, threading, time
from lib.proto import Proto, StreamParser
from lib.schema_codec import SchemaCodec
from django.conf import settings

class GlobalDiscovery:
    def __init__(self, broadcast_port=9000, listen_port=9001):
        self.broadcast_port = broadcast_port
        self.listen_port = listen_port
        self.running = False
        self.devices = {} # {slave_id: {ip, info, status}}

    def start(self):
        self.running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def trigger_once(self):
        """
        優化後的廣播發送
        """
        from .consumers import store
        
        cmd_def = store.get('0x1001')
        print(cmd_def)

        try:
            # 建立一個測試連線來獲取當前伺服器的內部實體 IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s_tmp:
                s_tmp.connect(('8.8.8.8', 80))
                local_ip = s_tmp.getsockname()[0]

            # 封裝 Protocol 數據包
            payload = SchemaCodec.encode(cmd_def, {
                "server_ip": local_ip,
                "ws_url": f"ws://{local_ip}:8000/ws/slave" # 注意：Django Channels 的 URL 路由必須對齊
            })
            pkt = Proto.pack(0x1001, payload)
            
            # 設置廣播 Socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                # 💡 技巧：針對特定子網廣播，或者發送給全域廣播
                sock.sendto(pkt, ('255.255.255.255', self.broadcast_port))
                
            print(f"🚀 [Discovery] Broadcast sent from {local_ip}")
            return True
        except Exception as e:
            print(f"❌ [Discovery] Failed: {e}")
            return False

    def _listen_loop(self):
        """監聽 Slave 主動報到 (Announce)"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', self.listen_port))
        parser = StreamParser()
        while self.running:
            try:
                raw, addr = sock.recvfrom(2048)
                parser.feed(raw)
                for ver, addr_id, cmd, payload in parser.pop():
                    if cmd == 0x1002: # ANNOUNCE
                        from .consumers import store
                        args = SchemaCodec.decode(store.get(0x1002), payload)
                        sid = args['slave_id']
                        self.devices[sid] = {"ip": addr[0], "hw": args['hw_version'], "last_seen": time.time()}
                        print(f"🎯 [Discovery] Device Reported: {sid}")
            except: continue

discovery_service = GlobalDiscovery()
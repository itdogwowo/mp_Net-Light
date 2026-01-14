# slave_controller/device_discovery.py
import socket
import threading
import time
import json
from datetime import datetime
import ipaddress
from django.conf import settings

class DeviceDiscovery:
    def __init__(self, broadcast_port=9000, listen_port=9001):
        self.broadcast_port = broadcast_port
        self.listen_port = listen_port
        self.devices = {}
        self.running = False
        self.lock = threading.Lock()
        
        # 自動檢測網絡
        self.local_ip = None
        self.broadcast_addr = None
        self.netmask = None
        self._detect_network()

        self.ws_port = getattr(settings, 'WEBSOCKET_PORT', 8000)
        print(f"[Discovery] 配置:")
        print(f"  WebSocket Port: {self.ws_port}")
    
    def _detect_network(self):
        """自動檢測本機 IP 和廣播地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            try:
                s.connect(('8.8.8.8', 80))
                self.local_ip = s.getsockname()[0]
            finally:
                s.close()
            
            if not self.local_ip:
                raise Exception("無法獲取本機 IP")
            
            try:
                import netifaces
                
                for interface in netifaces.interfaces():
                    addrs = netifaces.ifaddresses(interface)
                    if netifaces.AF_INET in addrs:
                        for addr_info in addrs[netifaces.AF_INET]:
                            if addr_info.get('addr') == self.local_ip:
                                self.netmask = addr_info.get('netmask', '255.255.255.0')
                                
                                network = ipaddress.IPv4Network(
                                    f"{self.local_ip}/{self.netmask}",
                                    strict=False
                                )
                                self.broadcast_addr = str(network.broadcast_address)
                                
                                print(f"[Discovery] 🌐 檢測到網絡配置:")
                                print(f"  本機 IP: {self.local_ip}")
                                print(f"  子網掩碼: {self.netmask}")
                                print(f"  廣播地址: {self.broadcast_addr}")
                                print(f"  網段: {network}")
                                return
                
                print(f"[Discovery] ⚠️ 未找到 netmask,使用備用方案")
                self._fallback_broadcast_calc()
                
            except ImportError:
                print(f"[Discovery] ℹ️ netifaces 未安裝,使用備用方案")
                self._fallback_broadcast_calc()
                
        except Exception as e:
            print(f"[Discovery] ⚠️ 網絡檢測失敗: {e},使用備用方案")
            self._fallback_broadcast_calc()
    

    def update_device_status(self, slave_id, status, ws_connected=False):
        """更新設備狀態"""
        with self.lock:
            if slave_id in self.devices:
                self.devices[slave_id]["status"] = status
                self.devices[slave_id]["ws_connected"] = ws_connected
                self.devices[slave_id]["last_seen"] = datetime.now().isoformat()
                print(f"[Discovery] 🔄 設備狀態更新: {slave_id} → {status}")

    def update_heartbeat(self, slave_id, heartbeat_data):
        """🔥 更新設備心跳數據"""
        with self.lock:
            if slave_id in self.devices:
                self.devices[slave_id].update({
                    "last_heartbeat": datetime.now().isoformat(),
                    "uptime_ms": heartbeat_data.get("uptime_ms", 0),
                    "mem_free": heartbeat_data.get("mem_free", 0),
                    "ws_connected": heartbeat_data.get("ws_connected", False),
                    "status": "online"
                })
                print(f"[Discovery] 💓 心跳更新: {slave_id}")

    def check_offline_devices(self):
        """🔥 檢查離線設備 (超過 30 秒未心跳)"""
        from datetime import datetime, timedelta
        
        with self.lock:
            now = datetime.now()
            for slave_id, device in self.devices.items():
                last_hb = device.get("last_heartbeat")
                
                # 如果有心跳記錄
                if last_hb:
                    try:
                        last_time = datetime.fromisoformat(last_hb)
                        if (now - last_time).total_seconds() > 30:
                            if device["status"] != "offline":
                                device["status"] = "offline"
                                device["ws_connected"] = False
                                print(f"[Discovery] ⚠️ 設備離線 (心跳超時): {slave_id}")
                    except Exception as e:
                        print(f"[Discovery] ⚠️ 解析心跳時間失敗: {slave_id} => {e}")
                
                # 如果從未收到心跳,但 last_seen 超過 60 秒
                elif device.get("last_seen"):
                    try:
                        last_seen_time = datetime.fromisoformat(device["last_seen"])
                        if (now - last_seen_time).total_seconds() > 60:
                            if device["status"] != "offline":
                                device["status"] = "offline"
                                device["ws_connected"] = False
                                print(f"[Discovery] ⚠️ 設備離線 (發現超時): {slave_id}")
                    except Exception as e:
                        print(f"[Discovery] ⚠️ 解析 last_seen 失敗: {slave_id} => {e}")
                        

    def _fallback_broadcast_calc(self):
        """備用方案:根據 IP 段猜測廣播地址"""
        if not self.local_ip:
            self.local_ip = '127.0.0.1'
        
        ip_parts = self.local_ip.split('.')
        
        if ip_parts[0] == '10':
            self.broadcast_addr = f"10.{ip_parts[1]}.255.255"
            self.netmask = "255.255.0.0"
        elif ip_parts[0] == '192' and ip_parts[1] == '168':
            self.broadcast_addr = f"192.168.{ip_parts[2]}.255"
            self.netmask = "255.255.255.0"
        elif ip_parts[0] == '172':
            self.broadcast_addr = f"172.{ip_parts[1]}.255.255"
            self.netmask = "255.255.0.0"
        else:
            self.broadcast_addr = "255.255.255.255"
            self.netmask = "255.255.255.0"
        
        print(f"[Discovery] 🌐 使用備用配置:")
        print(f"  本機 IP: {self.local_ip}")
        print(f"  子網掩碼: {self.netmask}")
        print(f"  廣播地址: {self.broadcast_addr}")
    
    def start(self):
        """啟動監聽服務(不自動廣播)"""
        if not self.broadcast_addr:
            print("[Discovery] ❌ 無法啟動:未檢測到網絡配置")
            return
        
        self.running = True
        
        # 🔥 只啟動監聽線程,不啟動廣播線程
        listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        listen_thread.start()
        
        print(f"[Discovery] ✅ 設備發現服務已啟動")
        print(f"[Discovery] 👂 監聽線程已啟動 (端口: {self.listen_port})")
        print(f"[Discovery] ℹ️ 請手動觸發設備發現")
    
    def stop(self):
        self.running = False
    
    # 🔥 新增:手動觸發單次發現
    def discover_once(self):
        """手動觸發一次設備發現"""
        if not self.broadcast_addr:
            return {"ok": False, "err": "網絡配置未初始化"}
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            try:
                sock.bind((self.local_ip, 0))
            except:
                sock.bind(('0.0.0.0', 0))
            
            message = json.dumps({
                "cmd": "DISCOVER",
                "server_ip": self.local_ip,
                # 🔥 使用正確的 port
                "ws_url": f"ws://{self.local_ip}:{self.ws_port}/ws/slave/",
                "timestamp": datetime.now().isoformat()
            })
            
            sock.sendto(
                message.encode('utf-8'),
                (self.broadcast_addr, self.broadcast_port)
            )
            
            sock.close()
            
            print(f"[Discovery] 📡 已發送發現廣播")
            print(f"[Discovery] 📡 WebSocket URL: ws://{self.local_ip}:{self.ws_port}/ws/slave/")
            
            return {"ok": True, "message": "發現廣播已發送"}
            
        except Exception as e:
            return {"ok": False, "err": str(e)}
    
    def _listen_loop(self):
        """接收 Slave 回應"""
        print(f"[Discovery] 👂 監聽循環已進入")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('', self.listen_port))
        sock.settimeout(1.0)
        
        print(f"[Discovery] 📥 開始監聽 UDP {self.listen_port} 端口")
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                print(f"[Discovery] 📬 收到數據 ({len(data)} bytes) 來自 {addr}")
                self._handle_response(data, addr)
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] ❌ 接收錯誤: {e}")
        
        sock.close()
        print(f"[Discovery] 👂 監聽循環已退出")
    
    def _handle_response(self, data, addr):
        """處理 Slave 回應"""
        try:
            msg = json.loads(data.decode('utf-8'))
            
            if msg.get('cmd') == 'SLAVE_ANNOUNCE':
                slave_id = msg.get('slave_id')
                ip = addr[0]
                
                with self.lock:
                    self.devices[slave_id] = {
                        "ip": ip,
                        "last_seen": datetime.now().isoformat(),
                        "status": "discovered",  # 🔥 改為 discovered,連接後才是 online
                        "pixel_count": msg.get('pixel_count', 0),
                        "hw_version": msg.get('hw_version', 'unknown'),
                        "ws_connected": False  # 🔥 新增 WebSocket 連接狀態
                    }
                
                print(f"[Discovery] 🎯 發現設備: Slave {slave_id} @ {ip}")
                
        except Exception as e:
            print(f"[Discovery] ❌ 解析回應錯誤: {e}")
    
    # 🔥 新增:發送 WebSocket 連接指令
    def connect_device(self, slave_id):
        """指示設備連接 WebSocket"""
        device = self.get_device(slave_id)
        if not device:
            return {"ok": False, "err": "設備未找到"}
        
        try:
            import socket as tcp_socket
            
            sock = tcp_socket.socket(tcp_socket.AF_INET, tcp_socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((device['ip'], 9000))
            
            # 🔥 使用您的 CMD 協議發送連接指令
            cmd = {
                "cmd": "WS_CONNECT",
                "url": f"ws://{self.local_ip}:8001/ws/slave/{slave_id}"
            }
            
            # TODO: 這裡應該用 proto.pack_packet()
            # 暫時用 JSON
            sock.send(json.dumps(cmd).encode('utf-8'))
            sock.close()
            
            print(f"[Discovery] 📤 已發送 WebSocket 連接指令到 Slave {slave_id}")
            return {"ok": True}
            
        except Exception as e:
            print(f"[Discovery] ❌ 發送連接指令失敗: {e}")
            return {"ok": False, "err": str(e)}
    
    def get_devices(self):
        """獲取設備列表"""
        with self.lock:
            return self.devices.copy()
    
    def get_device(self, slave_id):
        """獲取單個設備"""
        with self.lock:
            return self.devices.get(slave_id)
    
    def get_network_info(self):
        """獲取網絡配置信息"""
        return {
            "local_ip": self.local_ip,
            "netmask": self.netmask,
            "broadcast_addr": self.broadcast_addr
        }

# 全局單例
discovery_service = DeviceDiscovery()
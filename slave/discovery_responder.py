# discovery_responder.py (修復版)
import socket
import json
from machine import unique_id

class DiscoveryResponder:
    """UDP 設備發現響應器"""
    
    def __init__(self, listen_port=9000, server_port=9001):
        self.listen_port = listen_port
        self.server_port = server_port
        self.running = False
        self.ws_callback = None
        
        # 自動生成 slave_id (MAC 地址)
        uid_bytes = unique_id()
        self.slave_id = "{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}".format(
            uid_bytes[0], uid_bytes[1], uid_bytes[2],
            uid_bytes[3], uid_bytes[4], uid_bytes[5]
        )
        
        # 創建 UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', self.listen_port))
        self.sock.settimeout(0.1)
        
        print(f"[Discovery] 初始化完成")
        print(f"[Discovery] Slave ID: {self.slave_id}")
        print(f"[Discovery] 監聽端口: {self.listen_port}")
    
    def set_ws_callback(self, callback):
        """設置 WebSocket 連接回調"""
        self.ws_callback = callback
        print(f"[Discovery] 已設置 WebSocket 回調")  # 🔥 新增調試信息
    
    def start(self):
        """啟動響應器"""
        self.running = True
        print(f"[Discovery] 響應器已啟動")
    
    def stop(self):
        """停止響應器"""
        self.running = False
        self.sock.close()
        print(f"[Discovery] 響應器已停止")
    
    def poll(self):
        """輪詢接收廣播"""
        if not self.running:
            return
        
        try:
            data, addr = self.sock.recvfrom(1024)
            self._handle_discover(data, addr)
        except OSError as e:
            if e.args[0] in (11, 116):  # EAGAIN 或 ETIMEDOUT
                pass
            else:
                print(f"[Discovery] 接收錯誤: {e}")
    
    def _handle_discover(self, data, addr):
        """🔥 處理 DISCOVER 廣播 (確保調用回調)"""
        try:
            msg = json.loads(data.decode('utf-8'))
            
            if msg.get('cmd') == 'DISCOVER':
                server_ip = msg.get('server_ip')
                ws_url_base = msg.get('ws_url')
                
                print(f"[Discovery] 收到發現廣播: {server_ip}")
                print(f"[Discovery] Base URL: {ws_url_base}")
                
                # 補全完整 WebSocket URL
                if ws_url_base.endswith('/'):
                    full_ws_url = ws_url_base + self.slave_id
                else:
                    full_ws_url = ws_url_base + '/' + self.slave_id
                
                print(f"[Discovery] 完整 URL: {full_ws_url}")
                
                # 回應 Server
                response = json.dumps({
                    "cmd": "SLAVE_ANNOUNCE",
                    "slave_id": self.slave_id,
                    "pixel_count": 400,
                    "hw_version": "ESP32-P4"
                })
                
                self.sock.sendto(
                    response.encode('utf-8'),
                    (server_ip, self.server_port)
                )
                
                print(f"[Discovery] 已回應 Server: {server_ip}")
                
                # 🔥 觸發 WebSocket 連接 (關鍵!)
                if self.ws_callback:
                    print(f"[Discovery] 🔥 調用 WebSocket 回調")  # 🔥 新增調試
                    self.ws_callback(full_ws_url)
                else:
                    print(f"[Discovery] ⚠️ WebSocket 回調未設置!")  # 🔥 警告
                
        except Exception as e:
            print(f"[Discovery] 處理廣播錯誤: {e}")
            import sys
            sys.print_exception(e)
# discovery_responder.py (修正版)
import socket
import json
import time
from machine import unique_id

class DiscoveryResponder:
    """UDP 設備發現響應器"""
    
    def __init__(self, listen_port=9000, server_port=9001):
        """
        初始化
        Args:
            listen_port: 監聽端口
            server_port: Server 監聽端口
        """
        self.listen_port = listen_port
        self.server_port = server_port
        self.sock = None
        self.running = False
        
        # 🔥 WebSocket 連接回調(稍後設置)
        self.ws_connect_callback = None
        
        # 生成唯一 Slave ID
        uid_bytes = unique_id()
        self.slave_id = "{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}".format(
                uid_bytes[0], uid_bytes[1], uid_bytes[2],
                uid_bytes[3], uid_bytes[4], uid_bytes[5]
            )

        
        self.device_info = {
            "slave_id": self.slave_id,
            "pixel_count": 400,
            "hw_version": "ESP32-P4-v1.0",
            "fw_version": "1.0.0"
        }
        
        print("[Discovery] Slave ID: {}".format(self.slave_id))
    
    def set_ws_callback(self, callback):
        """設置 WebSocket 連接回調函數"""
        self.ws_connect_callback = callback
    
    def start(self):
        """啟動響應器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('', self.listen_port))
            self.sock.settimeout(1.0)
            
            self.running = True
            print("[Discovery] UDP 響應器已啟動 (port {})".format(self.listen_port))
            
        except Exception as e:
            print("[Discovery] 啟動失敗: {}".format(e))
    
    def stop(self):
        """停止響應器"""
        self.running = False
        if self.sock:
            self.sock.close()
        print("[Discovery] UDP 響應器已停止")
    
    def poll(self):
        """輪詢處理(非阻塞)"""
        if not self.running or not self.sock:
            return
        
        try:
            data, addr = self.sock.recvfrom(1024)
            self._handle_message(data, addr)
            
        except OSError:
            pass
        except Exception as e:
            print("[Discovery] 接收錯誤: {}".format(e))
    
    def _handle_message(self, data, addr):
        """處理收到的消息"""
        try:
            msg = json.loads(data.decode('utf-8'))
            
            if msg.get('cmd') == 'DISCOVER':
                print("[Discovery] 收到發現廣播: {}".format(addr[0]))
                
                # 獲取 WebSocket URL
                ws_url_template = msg.get('ws_url')
                if ws_url_template:
                    ws_url = ws_url_template + self.slave_id
                    print("[Discovery] WebSocket URL: {}".format(ws_url))
                    
                    # 🔥 觸發 WebSocket 連接
                    if self.ws_connect_callback:
                        self.ws_connect_callback(ws_url)
                
                # 發送回應
                response = json.dumps({
                    "cmd": "SLAVE_ANNOUNCE",
                    "slave_id": self.device_info["slave_id"],
                    "pixel_count": self.device_info["pixel_count"],
                    "hw_version": self.device_info["hw_version"],
                    "fw_version": self.device_info["fw_version"]
                })
                
                server_ip = addr[0]
                self.sock.sendto(
                    response.encode('utf-8'),
                    (server_ip, self.server_port)
                )
                
                print("[Discovery] 已回應 Server: {}".format(server_ip))
                
        except ValueError:
            pass
        except Exception as e:
            print("[Discovery] 處理消息錯誤: {}".format(e))
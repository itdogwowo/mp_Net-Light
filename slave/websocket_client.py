# websocket_client.py - WebSocket 客戶端(CMD 協議版 - 修正版)
import socket
import json
import struct
import time

class WebSocketClient:
    """WebSocket 客戶端 - 支援 CMD 二進位協議"""
    
    def __init__(self, app):
        self.ws = None
        self.connected = False
        self.url = None
        self.app = app  # 引用 App 實例(包含 dispatcher)
        
        # StreamParser 用於解析 CMD 封包
        from lib.proto import StreamParser
        self.parser = StreamParser(max_len=8192)
    
    def connect(self, url):
        """連接到 WebSocket"""
        self.url = url
        
        try:
            # 解析 URL: ws://10.10.1.27:8000/ws/slave/30EDA0EA4EC8
            if not url.startswith('ws://'):
                print("[WebSocket] 錯誤: 只支援 ws://")
                return False
            
            url_parts = url[5:].split('/', 1)
            host_port = url_parts[0]
            path = '/' + url_parts[1] if len(url_parts) > 1 else '/'
            
            if ':' in host_port:
                host, port = host_port.split(':')
                port = int(port)
            else:
                host = host_port
                port = 80
            
            print("[WebSocket] 正在連接: {}:{}{}".format(host, port, path))
            
            # 創建 TCP 連接
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, port))
            
            # 發送 WebSocket 握手
            import binascii
            key = binascii.b2a_base64(b'1234567890123456').decode().strip()
            
            handshake = (
                "GET {} HTTP/1.1\r\n"
                "Host: {}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Key: {}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                "\r\n"
            ).format(path, host, key)
            
            self.sock.send(handshake.encode('utf-8'))
            
            # 接收握手回應
            response = self.sock.recv(1024).decode('utf-8')
            
            if '101 Switching Protocols' in response:
                self.connected = True
                self.sock.settimeout(0)  # 非阻塞
                print("[WebSocket] 連接成功")
                return True
            else:
                print("[WebSocket] 握手失敗")
                self.sock.close()
                return False
                
        except Exception as e:
            print("[WebSocket] 連接失敗: {}".format(e))
            if hasattr(self, 'sock'):
                self.sock.close()
            return False
    
    def disconnect(self):
        """斷開連接"""
        if self.sock:
            self.sock.close()
            self.sock = None
        self.connected = False
        print("[WebSocket] 已斷開連接")
    
    def poll(self):
        """輪詢接收數據(非阻塞)"""
        if not self.connected or not self.sock:
            return
        
        try:
            data = self.sock.recv(4096)
            if data:
                self._handle_websocket_frame(data)
        except OSError:
            pass
        except Exception as e:
            print("[WebSocket] 接收錯誤: {}".format(e))
    
    def _handle_websocket_frame(self, frame_data):
        """處理 WebSocket 幀"""
        if len(frame_data) < 2:
            return
        
        # 解析 WebSocket 幀頭
        fin = (frame_data[0] & 0x80) != 0
        opcode = frame_data[0] & 0x0F
        masked = (frame_data[1] & 0x80) != 0
        payload_len = frame_data[1] & 0x7F
        
        offset = 2
        
        # 處理擴展長度
        if payload_len == 126:
            payload_len = struct.unpack('>H', frame_data[2:4])[0]
            offset = 4
        elif payload_len == 127:
            payload_len = struct.unpack('>Q', frame_data[2:10])[0]
            offset = 10
        
        # 提取 payload
        if offset + payload_len > len(frame_data):
            print("[WebSocket] 幀數據不完整")
            return
        
        payload = frame_data[offset:offset+payload_len]
        
        # 根據 opcode 處理
        if opcode == 0x01:  # 文本幀
            self._handle_text_message(payload.decode('utf-8'))
        elif opcode == 0x02:  # 二進位幀
            self._handle_binary_message(payload)
        elif opcode == 0x08:  # 關閉幀
            print("[WebSocket] 收到關閉幀")
            self.disconnect()
    
    def _handle_text_message(self, text):
        """處理文本消息(暫不使用)"""
        print("[WebSocket] 收到文本: {}".format(text[:50]))
    
    def _handle_binary_message(self, data):
        """
        處理二進位消息 - CMD 協議封包
        交給 StreamParser 解析
        """
        # 🔥 關鍵:使用 StreamParser
        self.parser.feed(data)
        
        # 🔥 修正: pop() 是生成器,需要用 for 循環迭代
        for ver, addr, cmd, payload in self.parser.pop():
            print("[WebSocket] 📥 收到 CMD: 0x{:04X}, LEN: {}".format(cmd, len(payload)))
            
            # 🔥 交給 dispatcher 處理
            ctx = {
                "app": self.app,
                "transport": "websocket",
                "send": self._send_cmd_packet
            }
            
            self.app.disp.dispatch(cmd, payload, ctx)
    
    def _send_cmd_packet(self, packet):
        """發送 CMD 封包(包裝成 WebSocket 二進位幀)"""
        if not self.connected or not self.sock:
            return
        
        # 構建 WebSocket 二進位幀
        # FIN=1, opcode=2 (binary), mask=1
        frame = bytearray()
        frame.append(0x82)  # FIN + opcode
        
        payload_len = len(packet)
        
        if payload_len < 126:
            frame.append(0x80 | payload_len)  # mask bit + length
        elif payload_len < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', payload_len))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack('>Q', payload_len))
        
        # Masking key (簡化用固定值)
        mask_key = b'\x12\x34\x56\x78'
        frame.extend(mask_key)
        
        # Masked payload
        masked_payload = bytearray(payload_len)
        for i in range(payload_len):
            masked_payload[i] = packet[i] ^ mask_key[i % 4]
        
        frame.extend(masked_payload)
        
        # 發送
        try:
            self.sock.send(bytes(frame))
            print("[WebSocket] 📤 已發送 CMD: {} bytes".format(len(packet)))
        except Exception as e:
            print("[WebSocket] 發送失敗: {}".format(e))
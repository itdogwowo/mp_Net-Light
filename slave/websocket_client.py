# websocket_client.py (詳細調試版)
import socket
import struct
import time

class WebSocketClient:
    """WebSocket 客戶端 - 詳細調試版"""
    
    def __init__(self, app):
        self.ws = None
        self.connected = False
        self.url = None
        self.app = app
        
        from lib.proto import StreamParser
        self.parser = StreamParser(max_len=8192)
        
        self.sock = None
    
    def connect(self, url):
        """連接到 WebSocket (詳細日誌版)"""
        self.url = url
        
        try:
            # 🔥 步驟 1: 解析 URL
            print("[WS-DEBUG] === 開始 WebSocket 連接流程 ===")
            print("[WS-DEBUG] 原始 URL: {}".format(url))
            
            if not url.startswith('ws://'):
                print("[WS-DEBUG] ❌ URL 格式錯誤")
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
            
            print("[WS-DEBUG] 解析結果:")
            print("[WS-DEBUG]   Host: {}".format(host))
            print("[WS-DEBUG]   Port: {}".format(port))
            print("[WS-DEBUG]   Path: {}".format(path))
            
            # 🔥 步驟 2: 創建 TCP 連接
            print("[WS-DEBUG] --- TCP 連接階段 ---")
            print("[WS-DEBUG] 創建 socket...")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)  # 🔥 增加超時時間到 10 秒
            
            print("[WS-DEBUG] 嘗試連接 {}:{}...".format(host, port))
            start_time = time.ticks_ms()
            
            try:
                self.sock.connect((host, port))
                connect_time = time.ticks_diff(time.ticks_ms(), start_time)
                print("[WS-DEBUG] ✅ TCP 連接成功! 耗時: {} ms".format(connect_time))
            except Exception as e:
                print("[WS-DEBUG] ❌ TCP 連接失敗: {}".format(e))
                print("[WS-DEBUG] 錯誤類型: {}".format(type(e)))
                self.sock.close()
                return False
            
            # 🔥 步驟 3: 發送 WebSocket 握手
            print("[WS-DEBUG] --- WebSocket 握手階段 ---")
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
            
            print("[WS-DEBUG] 發送握手請求:")
            print("[WS-DEBUG] ---START---")
            print(handshake)
            print("[WS-DEBUG] ---END---")
            print("[WS-DEBUG] 握手長度: {} bytes".format(len(handshake)))
            
            try:
                sent = self.sock.send(handshake.encode('utf-8'))
                print("[WS-DEBUG] ✅ 已發送: {} bytes".format(sent))
            except Exception as e:
                print("[WS-DEBUG] ❌ 發送握手失敗: {}".format(e))
                self.sock.close()
                return False
            
            # 🔥 步驟 4: 接收握手回應
            print("[WS-DEBUG] 等待 Server 回應...")
            self.sock.settimeout(5)
            
            try:
                response = self.sock.recv(1024)
                print("[WS-DEBUG] ✅ 收到回應: {} bytes".format(len(response)))
                print("[WS-DEBUG] ---回應內容---")
                
                # 🔥 修復:不使用 errors 參數
                try:
                    response_text = response.decode('utf-8')  # ✅ 移除 errors='ignore'
                except:
                    # 如果解碼失敗,嘗試忽略錯誤字節
                    response_text = ""
                    for b in response:
                        try:
                            response_text += chr(b)
                        except:
                            response_text += "?"
                
                print(response_text)
                print("[WS-DEBUG] ---END---")
                
            except Exception as e:
                print("[WS-DEBUG] ❌ 接收回應失敗: {}".format(e))
                print("[WS-DEBUG] 錯誤類型: {}".format(type(e)))
                self.sock.close()
                return False
            
            # 🔥 步驟 5: 驗證握手回應
            if '101 Switching Protocols' in response_text:
                print("[WS-DEBUG] ✅ 握手成功! 切換到 WebSocket 協議")
                self.connected = True
                self.sock.settimeout(0)
                print("[WS-DEBUG] === WebSocket 連接建立完成 ===")
                return True
            else:
                print("[WS-DEBUG] ❌ 握手失敗! 未收到 101 狀態碼")
                print("[WS-DEBUG] 實際回應: {}".format(response_text[:100]))
                self.sock.close()
                return False
                
        except Exception as e:
            print("[WS-DEBUG] ❌ 連接過程異常: {}".format(e))
            print("[WS-DEBUG] 異常類型: {}".format(type(e)))
            if self.sock:
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
        """輪詢接收數據"""
        if not self.connected or not self.sock:
            return
        
        try:
            data = self.sock.recv(4096)
            if data:
                print("[WS-DEBUG] 📩 收到原始數據: {} bytes".format(len(data)))
                self._handle_websocket_frame(data)
        except OSError:
            pass
        except Exception as e:
            print("[WebSocket] 接收錯誤: {}".format(e))
    
    def _handle_websocket_frame(self, frame_data):
        """處理 WebSocket 幀"""
        print("[WS-DEBUG] 🔍 開始解析幀: {} bytes".format(len(frame_data)))

        if len(frame_data) < 2:
            print("[WS-DEBUG] ⚠️ 幀數據太短")
            return

        opcode = frame_data[0] & 0x0F
        payload_len = frame_data[1] & 0x7F
        offset = 2

        print("[WS-DEBUG] 幀信息: opcode=0x{:02X}, payload_len={}".format(opcode, payload_len))

        # 處理擴展長度
        if payload_len == 126:
            payload_len = struct.unpack('>H', frame_data[2:4])[0]
            offset = 4
        elif payload_len == 127:
            payload_len = struct.unpack('>Q', frame_data[2:10])[0]
            offset = 10

        if offset + payload_len > len(frame_data):
            print("[WebSocket] 幀數據不完整")
            return

        payload = frame_data[offset:offset+payload_len]
        print("[WS-DEBUG] 提取 payload: {} bytes".format(len(payload)))

        # 🔥 根據 opcode 處理
        if opcode == 0x01:  # 文本幀
            print("[WS-DEBUG] 處理文本幀")
            self._handle_text_message(payload.decode('utf-8'))

        elif opcode == 0x02:  # 二進位幀
            print("[WS-DEBUG] 處理二進位幀")
            self._handle_binary_message(payload)

        elif opcode == 0x08:  # 關閉幀
            print("[WebSocket] 收到關閉幀")
            self.disconnect()

        elif opcode == 0x09:  # 🔥 Ping 幀
            print("[WS-DEBUG] 收到 Ping,回應 Pong")
            self._send_pong(payload)

        elif opcode == 0x0A:  # 🔥 Pong 幀
            print("[WS-DEBUG] 收到 Pong")

        else:
            print("[WS-DEBUG] ⚠️ 未知 opcode: 0x{:02X}".format(opcode))
            
            
    def _send_pong(self, payload):
        """🔥 回應 Pong 幀"""
        if not self.connected or not self.sock:
            return
        
        # 構建 Pong 幀 (opcode=0x0A)
        frame = bytearray()
        frame.append(0x8A)  # FIN=1, opcode=0x0A (Pong)
        
        payload_len = len(payload)
        
        if payload_len < 126:
            frame.append(0x80 | payload_len)
        elif payload_len < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', payload_len))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack('>Q', payload_len))
        
        # Masking key
        mask_key = b'\x12\x34\x56\x78'
        frame.extend(mask_key)
        
        # Masked payload
        masked_payload = bytearray(payload_len)
        for i in range(payload_len):
            masked_payload[i] = payload[i] ^ mask_key[i % 4]
        
        frame.extend(masked_payload)
        
        try:
            self.sock.send(bytes(frame))
            print("[WS-DEBUG] 已發送 Pong")
        except Exception as e:
            print("[WebSocket] 發送 Pong 失敗: {}".format(e))
    
    def _handle_text_message(self, text):
        """處理文本消息"""
        print("[WebSocket] 收到文本: {}".format(text[:50]))
    
    def _handle_binary_message(self, data):
        """處理二進位消息"""
        print("[WS-DEBUG] 🔥 進入 _handle_binary_message: {} bytes".format(len(data)))
        
        self.parser.feed(data)
        
        try:
            packet_count = 0
            for ver, addr, cmd, payload in self.parser.pop():
                packet_count += 1
                print("[WS-DEBUG] 📦 解析封包 #{}: cmd=0x{:04X}".format(packet_count, cmd))
                
                cmd_name = "UNKNOWN"
                cmd_def = self.app.store.get(cmd)
                if cmd_def:
                    cmd_name = cmd_def.get("name", "UNKNOWN")
                
                print("[WS] 📥 收到 CMD: 0x{:04X} ({}) - {} bytes".format(
                    cmd, cmd_name, len(payload)
                ))
                
                ctx = {
                    "app": self.app,
                    "transport": "websocket",
                    "send": self._send_cmd_packet
                }
                
                self.app.disp.dispatch(cmd, payload, ctx)
            
            if packet_count == 0:
                print("[WS-DEBUG] ⚠️ StreamParser 沒有解析出任何封包")
        
        except Exception as e:
            print("[WS] ❌ 處理封包錯誤: {}".format(e))
            import sys
            sys.print_exception(e)
    
    def _send_cmd_packet(self, packet):
        """發送 CMD 封包"""
        if not self.connected or not self.sock:
            return
        
        frame = bytearray()
        frame.append(0x82)
        
        payload_len = len(packet)
        
        if payload_len < 126:
            frame.append(0x80 | payload_len)
        elif payload_len < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack('>H', payload_len))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack('>Q', payload_len))
        
        mask_key = b'\x12\x34\x56\x78'
        frame.extend(mask_key)
        
        masked_payload = bytearray(payload_len)
        for i in range(payload_len):
            masked_payload[i] = packet[i] ^ mask_key[i % 4]
        
        frame.extend(masked_payload)
        
        try:
            self.sock.send(bytes(frame))
            print("[WebSocket] 📤 已發送 CMD: {} bytes".format(len(packet)))
        except Exception as e:
            print("[WebSocket] 發送失敗: {}".format(e))
import socket
import struct
import time
from lib.sys_bus import bus

class NetBus:
    """
    NetBus: 整合 TCP/WS/UDP 的大一統總線
    內建 Parser 隔離，支持自動解析或原始數據讀取
    """
    TYPE_TCP = 0
    TYPE_WS  = 1
    TYPE_UDP = 2

    def __init__(self, bus_type=TYPE_WS, app=None, label="Bus"):
        self.type = bus_type
        self.label = label
        self.app = app
        self.sock = None
        self.connected = False
        self.target_addr = None # UDP 發送對象
        
        # 內存隔離：每個 Bus 實例擁有獨立的緩衝區與解析器
        # 統一使用 Buffer.size 作為接收緩衝區大小
        # 🚀 增大默認緩衝區以容納完整 WS 幀 (Header + Payload)
        # 嘗試 64KB 大包 (配合 BufferHub 64KB)
        buf_size = bus.shared.get('Buffer', {}).get('size', 65536)
        self._buf = bytearray(buf_size)
        self._ptr = 0
        self.parser = app.create_parser() if app else None

    def enter_raw_mode(self, target_hub, size):
        """進入 Raw Mode: 直接將 Socket 數據導向 Hub"""
        self.raw_mode = True
        self.raw_bytes_left = size
        self.raw_target = target_hub
        # 預先分配一個與 Socket 操作相關的 memoryview，減少循環中的創建開銷
        # 注意：這裡使用整個緩衝區，具體長度在 readinto 時限制
        self._raw_view_cache = memoryview(self._buf)
        print(f"🚀 [NetBus] Entered RAW MODE. Expecting {size} bytes.")

    def connect(self, host, port, path="/ws"):
        """初始化連接 (TCP/WS) 或 綁定 (UDP)"""
        try:
            if self.type == self.TYPE_UDP:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.bind(('0.0.0.0', port))
                self.connected = True
            else:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5)
                self.sock.connect((host, port))
                
                if self.type == self.TYPE_WS:
                    # WebSocket 握手邏輯
                    handshake = (
                        f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n"
                    )
                    self.sock.send(handshake.encode())
                    if b"101 Switching Protocols" not in self.sock.recv(1024):
                        raise Exception("WS Handshake Failed")
                
                self.connected = True
            
            self.sock.settimeout(0)  # 統一進入非阻塞模式
            print(f"✅ [{self.label}] Initialized")
            return True
        except Exception as e:
            print(f"❌ [{self.label}] Init Failed: {e}")
            return False
        
    def disconnect(self):
        """全面清除現有的網路連接資源"""
        if not self.sock:
            self.connected = False
            return
            
        try:
            # 針對不同類型的協議做優雅收尾
            if self.type == self.TYPE_WS and self.connected:
                # 嘗試發送 WS 關閉幀 (Opcode 0x8)
                try: self.sock.send(b'\x88\x00') 
                except: pass
            
            # 關閉 Socket (TCP/UDP/WS 均適用)
            self.sock.close()
        except OSError:
            pass
        finally:
            self.sock = None
            self.connected = False
            self.target_addr = None
            self._ptr = 0 # 清空緩衝區指針
            print(f"🔌 [{self.label}] Connection Closed.")

    def poll(self, **extra_ctx):
        """
        核心智能輪詢：
        1. 從網路吸取數據
        2. 如果有 app，自動處理 NL3 協議
        3. 處理失敗自動標記斷線
        """
        if not self.connected or not self.sock: return
        
        # RAW MODE HANDLER
        if getattr(self, 'raw_mode', False):
            try:
                # 🚀 Zero-Copy Optimization:
                # Use existing self._buf to avoid allocating new bytes object
                # This prevents GC spikes during high-speed transfer
                
                # 1. Read directly into pre-allocated buffer (limit to remaining bytes)
                # 使用緩存的 memoryview 進行切片，避免每次創建新的 memoryview 對象
                limit = min(len(self._buf), self.raw_bytes_left)
                
                # 這裡的切片操作在 MicroPython 中是非常輕量的
                view = self._raw_view_cache[:limit]
                n = self.sock.readinto(view)
                
                if n is None: # Non-blocking, no data
                    return
                    
                if n == 0: # Connection closed
                    self.connected = False
                    return
                
                # 2. Write to Hub using memoryview (no copy if Hub supports it, or fast C-level copy)
                if self.raw_target:
                    # 使用已經讀入數據的 view 切片
                    self.raw_target.write_from(view[:n])
                
                self.raw_bytes_left -= n
                
                if self.raw_bytes_left <= 0:
                    self.raw_mode = False
                    self._raw_view_cache = None # 釋放引用
                    print(f"🏁 [NetBus] RAW MODE DONE.")
            except OSError:
                pass
            return

        try:
            # 確保接收大小與緩衝區一致
            recv_size = bus.shared.get('Buffer', {}).get('size', 65536)
            if self.type == self.TYPE_UDP:
                raw, addr = self.sock.recvfrom(recv_size)
                self.target_addr = addr # 自動鎖定最後一個來源
            else:
                raw = self.sock.recv(recv_size)
                if not raw: 
                    self.connected = False
                    return

            # --- 解析數據 (WS 剝皮 或 直接取用) ---
            data = raw
            if self.type == self.TYPE_WS:
                # 簡易 WS 解幀 (忽略 Mask, 只取 Payload)
                off = 2
                pl_len = raw[1] & 0x7F
                if pl_len == 126: off = 4
                elif pl_len == 127: off = 10
                data = raw[off:]

            # --- 智能分發 ---
            if self.app and self.parser:
                # 針對 WS 模式，嘗試避免內存複製 (如果 parser 支援)
                # 但 StreamParser.feed 目前是 extend
                self.app.handle_stream(
                    self.parser, data, 
                    transport_name=self.label, 
                    send_func=self.write,
                    **extra_ctx
                )
            else:
                # 手動模式：存入緩衝區供 readinto 讀取
                l = len(data)
                self._buf[:l] = data
                self._ptr = l

        except OSError:
            pass # 沒有數據

    def write(self, data: bytes):
        """大一統寫入"""
        if not self.connected: return
        try:
            if self.type == self.TYPE_UDP:
                if self.target_addr: self.sock.sendto(data, self.target_addr)
            elif self.type == self.TYPE_WS:
                # 簡單 WS 封裝
                hdr = bytearray([0x82])
                l = len(data)
                if l < 126: hdr.append(l)
                else: hdr.append(126); hdr.extend(struct.pack(">H", l))
                self.sock.send(hdr + data)
            else:
                self.sock.send(data)
        except:
            self.connected = False

    def any(self): return self._ptr
    
    def readinto(self, buf):
        ln = self._ptr
        buf[:ln] = self._buf[:ln]
        self._ptr = 0
        return ln
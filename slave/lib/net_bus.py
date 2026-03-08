import socket
import struct
import time
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub

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
        # 🚀 升級為 AtomicStreamHub (Triple Buffering)
        # 配合 sys_bus.shared['decode_core'] 實現動態 CPU 解碼
        
        # 從 Config 中讀取 buffer 設置，支援動態結構
        # 默認: size=65536, count=3
        buf_conf = bus.shared.get('Buffer', {})
        buf_size = buf_conf.get('size', 65536)
        buf_count = buf_conf.get('count', 3)
        
        # 建立 Triple Buffering (或 Config 指定的數量)
        self.hub = AtomicStreamHub(buf_size, buf_count, name=label)
        self._ptr = 0
        self.parser = app.create_parser() if app else None
        
        # 預先緩存 hub 的 memoryview 以供 readinto 使用
        self._hub_view_cache = None

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
        1. Network -> Hub (使用 Triple Buffering)
        2. Hub -> Parser (根據 sys_bus.shared['decode_core'] 決定由誰調用)
        """
        if not self.connected or not self.sock: return
        
        # --- RAW MODE (Bypass Hub/Parser) ---
        if getattr(self, 'raw_mode', False):
             # [Raw Mode logic unchanged...]
             # 這裡省略，保持原樣，因為 Raw Mode 已經是 Zero-Copy 到目標 Hub
             self._poll_raw_mode()
             return

        # --- NORMAL MODE: Network -> Hub ---
        try:
            # 1. 嘗試獲取 Hub 的寫入視圖 (Zero-Copy)
            w_view = self.hub.get_write_view()
            if w_view:
                # 2. 直接讀入 Hub (Socket -> RAM)
                # 使用 readinto 避免分配
                try:
                    # 注意: socket.readinto 在非阻塞模式下可能返回 None
                    # 如果是 UDP，我們需要 recvfrom_into (但 MicroPython 的 UDP readinto 支援有限)
                    if self.type == self.TYPE_UDP:
                        # UDP 暫時保持舊方式 (因為要獲取 addr)
                        # 或者使用 recvfrom_into (如果支持)
                        # 這裡為簡單起見，TCP/WS 使用高效路徑，UDP 保持兼容
                        raw, addr = self.sock.recvfrom(len(w_view))
                        self.target_addr = addr
                        n = len(raw)
                        w_view[:n] = raw # copy into hub
                    else:
                        n = self.sock.readinto(w_view)
                    
                    if n:
                        # 3. 提交寫入 (Make available to reader)
                        # AtomicStreamHub 已升級支援 commit(length)
                        self.hub.commit(n)
                        
                except OSError:
                    pass
        except Exception as e:
            pass
            
        # 3. 觸發數據處理 (如果是 Core 0 解碼模式)
        # 預設 decode_core 為 0 (Core 0)
        decode_core = bus.shared.get('decode_core', 0)
        if decode_core == 0:
            self.process_ingress()

    def process_ingress(self):
        """
        從 Hub 讀取數據並進行協議解析 (WS/NL3)
        可由 Core 0 或 Core 1 調用
        """
        if not self.app or not self.parser: return
        
        # 嘗試從 Hub 獲取數據塊
        # get_read_view 現在返回切片後的 memoryview (長度正確)
        view = self.hub.get_read_view()
        if view:
            # --- 解析數據 (WS 剝皮) ---
            # 注意: 這裡的數據可能是不完整的 WS 幀，或者是多個幀
            # 我們假設 Parser 能處理流式數據
            
            data = view
            if self.type == self.TYPE_WS:
                # 簡易 WS 解幀 (忽略 Mask, 只取 Payload)
                # ⚠️ 限制：這裡假設 WS Frame Header 完整在 view 開頭
                # 如果 Header 被切斷 (極少見，因為 view 是 64KB)，這裡會出錯
                # TODO: 實現更健壯的流式 WS Parser
                if len(view) > 2:
                    off = 2
                    pl_len = view[1] & 0x7F
                    if pl_len == 126: off = 4
                    elif pl_len == 127: off = 10
                    data = view[off:]
                else:
                    return # Header incomplete

            # --- 智能分發 ---
            try:
                self.app.handle_stream(
                    self.parser, data, 
                    transport_name=self.label, 
                    send_func=self.write
                )
            except Exception as e:
                print(f"❌ [NetBus] Process Error: {e}")

    def _poll_raw_mode(self):
        try:
            # 🚀 Zero-Copy Optimization:
            # Use existing self._buf to avoid allocating new bytes object
            # This prevents GC spikes during high-speed transfer
            
            # 1. Read directly into pre-allocated buffer (limit to remaining bytes)
            # 使用緩存的 memoryview 進行切片，避免每次創建新的 memoryview 對象
            # 注意: Raw Mode 下我們繞過 Hub 的 Normal Buffer，直接用 self._buf (或者 Hub 的 buffer?)
            # 為了兼容性，我們這裡還是用 self._buf 讀取，然後 write_from 到 target_hub
            # 但既然我們有了 self.hub，我們可以借用 self.hub 的 buffer 嗎？
            # 為了簡單起見，Raw Mode 保持原來的邏輯 (使用 self._buf)
            # 因為 Raw Mode 是要把數據寫入 *另一個* Hub (stream hub)，而不是 self.hub (ingress hub)
            
            if not self._raw_view_cache:
                # Lazy init cache if needed (should be done in enter_raw_mode)
                self._raw_view_cache = memoryview(self._buf)

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
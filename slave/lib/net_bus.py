import socket
import struct
import time

class NetBus:
    """
    NetBus: 整合 TCP/WS/UDP 的大一統總線
    🚀 升級版：使用 16KB 大緩衝區 + recv_into 零拷貝接收
    """
    TYPE_TCP = 0
    TYPE_WS  = 1
    TYPE_UDP = 2
    
    # 默認接收緩衝區大小 (16KB)
    DEFAULT_BUF_SIZE = 16384

    def __init__(self, bus_type=TYPE_WS, app=None, label="Bus", buf_size=None):
        self.type = bus_type
        self.label = label
        self.app = app
        self.sock = None
        self.connected = False
        self.target_addr = None # UDP 發送對象
        
        # 保存當前連接信息，用於避免重複連接
        self.host = None
        self.port = None
        
        # 🚀 內存優化：預分配大塊緩衝區
        # 優先使用傳入的 buf_size，否則使用默認值
        real_size = buf_size if buf_size else self.DEFAULT_BUF_SIZE
        self._buf = bytearray(real_size)
        self._view = memoryview(self._buf)
        self._ptr = 0 # 用於手動 readinto 模式的有效數據長度
        
        self.parser = app.create_parser() if app else None

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
                    # 握手回應較短，使用普通 recv 即可
                    if b"101 Switching Protocols" not in self.sock.recv(1024):
                        raise Exception("WS Handshake Failed")
                
                self.connected = True
            
            # 保存當前連接信息
            self.host = host
            self.port = port
            
            self.sock.settimeout(0)  # 統一進入非阻塞模式
            print(f"✅ [{self.label}] Initialized")
            return True
        except Exception as e:
            print(f"❌ [{self.label}] Init Failed: {e}")
            self.connected = False
            return False
        
    def disconnect(self):
        """全面清除現有的網路連接資源"""
        if not self.sock:
            self.connected = False
            self.host = None
            self.port = None
            return
            
        try:
            if self.type == self.TYPE_WS and self.connected:
                try: self.sock.send(b'\x88\x00') 
                except: pass
            
            self.sock.close()
        except OSError:
            pass
        finally:
            self.sock = None
            self.connected = False
            self.target_addr = None
            self._ptr = 0
            self.host = None
            self.port = None
            print(f"🔌 [{self.label}] Connection Closed.")

    def poll(self, **extra_ctx):
        """
        核心智能輪詢：
        🚀 使用 recv_into 實現零拷貝接收
        """
        if not self.connected or not self.sock: return
        
        try:
            n = 0
            if self.type == self.TYPE_UDP:
                # UDP recvfrom_into 在某些 MicroPython 版本可能不支援，這裡保留 recvfrom
                # 如果追求極致 UDP 性能，可嘗試 recvfrom_into
                raw, addr = self.sock.recvfrom(2048)
                self.target_addr = addr
                # 為了兼容下方邏輯，手動複製到 _buf (UDP 通常包小，影響不大)
                n = len(raw)
                self._buf[:n] = raw
            else:
                # TCP/WS 使用 recv_into
                # 嘗試讀取，直到填滿緩衝區或沒數據
                try:
                    if hasattr(self.sock, 'recv_into'):
                        n = self.sock.recv_into(self._view)
                    else:
                        n = self.sock.readinto(self._view)
                    
                    # 關鍵修復：recv_into/readinto 在非阻塞模式下可能返回 None
                    if n is None: return

                except AttributeError:
                    # Fallback
                    raw = self.sock.recv(len(self._buf)) # 使用真實 buffer 大小
                    if raw:
                        n = len(raw)
                        self._buf[:n] = raw
                    else:
                        n = 0

                # 關鍵修復：recv_into/readinto 在非阻塞模式下可能返回 None
                # 注意: 之前的代碼段中已經處理了 n is None 的情況並 return
                # 所以這裡 n 要麼是整數，要麼已經 return
                if n is None: return

                if n == 0: 
                    # 對端關閉連接 (recv 返回 0)
                    self.connected = False
                    return

            # --- 數據處理 (基於 memoryview) ---
            
            # 獲取有效數據的切片
            data_view = self._view[:n]
            payload_view = data_view

            if self.type == self.TYPE_WS:
                # 簡易 WS 解幀 (忽略 Mask, 只取 Payload)
                # 注意：這裡假設一個 TCP 包包含一個完整的 WS Frame Header
                # 如果 Header 被切分，這裡會出錯。但在高速 LAN 環境下，通常 Header 會隨數據一起到達。
                if n > 2:
                    off = 2
                    # 讀取第二個字節的低 7 位 (Payload Length)
                    pl_len = self._buf[1] & 0x7F
                    if pl_len == 126: off = 4
                    elif pl_len == 127: off = 10
                    
                    # 如果數據長度足夠包含 Header
                    if n > off:
                        payload_view = data_view[off:]
                    else:
                        # 數據太短，無法剝離 WS Header
                        # 策略：直接透傳給 StreamParser，讓它自己去尋找 SOF (NL)
                        # StreamParser 具有抗噪能力，會忽略前面的 WS Header 字節
                        payload_view = data_view

            # --- 智能分發 ---
            if self.app and self.parser:
                # 自動餵入專屬 Parser
                self.app.handle_stream(
                    self.parser, payload_view, 
                    transport_name=self.label, 
                    send_func=self.write,
                    **extra_ctx
                )
            else:
                # 手動模式：更新指針供 readinto 讀取
                # 注意：這裡會覆蓋舊數據，如果上層處理不夠快會丟數據
                # 但對於輪詢模式，通常是 poll -> read -> poll
                self._ptr = len(payload_view)
                # 如果 payload_view 不是從 0 開始，需要搬移嗎？
                # 為了簡化，如果是手動模式，建議直接讀取 _buf[:_ptr]
                # 但如果 WS 剝離了 Header，數據在 _buf[off:]
                # 這裡做一個內存移動，確保 readinto 讀到的是 Payload
                if self.type == self.TYPE_WS and payload_view is not data_view:
                     l = len(payload_view)
                     self._buf[:l] = payload_view
                     self._ptr = l
                else:
                     self._ptr = n

        except OSError:
            pass # 沒有數據 (EAGAIN)

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
                elif l < 65536: hdr.append(126); hdr.extend(struct.pack(">H", l))
                else: hdr.append(127); hdr.extend(struct.pack(">Q", l))
                self.sock.send(hdr + data)
            else:
                self.sock.send(data)
        except:
            self.connected = False

    def any(self): return self._ptr
    
    def readinto(self, buf):
        ln = self._ptr
        if ln > len(buf): ln = len(buf)
        buf[:ln] = self._buf[:ln]
        self._ptr = 0
        return ln

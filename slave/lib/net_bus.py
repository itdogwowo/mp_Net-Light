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
        self._peer = None
        
        # 內存隔離：每個 Bus 實例擁有獨立的緩衝區與解析器
        # 統一使用 Buffer.size 作為接收緩衝區大小
        buf_cfg = bus.shared.get('Buffer', {}) or {}
        buf_size = buf_cfg.get('size', 4096)
        self._buf = bytearray(buf_size)
        self._ptr = 0
        self.parser = app.create_parser() if app else None
        self.rx_hub = None
        rx_buffers = int(buf_cfg.get("rx_hub_buffers", 0) or 0)
        if rx_buffers > 0:
            self.rx_hub = AtomicStreamHub(buf_size, num_buffers=rx_buffers)

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
            if self.type == self.TYPE_UDP:
                self._peer = ("0.0.0.0", port, "")
            else:
                self._peer = (host, port, path)
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
            self._peer = None
            print(f"🔌 [{self.label}] Connection Closed.")

    def poll(self, **extra_ctx):
        """
        核心智能輪詢：
        1. 從網路吸取數據
        2. 如果有 app，自動處理 NL3 協議
        3. 處理失敗自動標記斷線
        """
        if not self.connected or not self.sock: return
        
        try:
            if self.rx_hub is not None:
                view = self.rx_hub.get_write_view()
                if view is None:
                    if self.type == self.TYPE_UDP:
                        try:
                            self.sock.recvfrom(1024)
                        except OSError:
                            pass
                    else:
                        try:
                            self.sock.recv(1024)
                        except OSError:
                            pass
                    return

                n = 0
                raw_mv = None
                if self.type == self.TYPE_UDP:
                    if hasattr(self.sock, "recvfrom_into"):
                        n, addr = self.sock.recvfrom_into(view)
                        self.target_addr = addr
                        raw_mv = view[:n]
                    else:
                        raw_bytes, addr = self.sock.recvfrom(len(view))
                        self.target_addr = addr
                        n = len(raw_bytes)
                        if n:
                            view[:n] = raw_bytes
                        raw_mv = view[:n]
                else:
                    if hasattr(self.sock, "recv_into"):
                        n = self.sock.recv_into(view)
                    elif hasattr(self.sock, "readinto"):
                        n = self.sock.readinto(view)
                    else:
                        raw_bytes = self.sock.recv(len(view))
                        n = len(raw_bytes)
                        if n:
                            view[:n] = raw_bytes
                    if n is None:
                        return
                    if n == 0:
                        self.connected = False
                        return
                    raw_mv = view[:n]

                raw = raw_mv
                self.rx_hub.commit()
            else:
                recv_size = len(self._buf)
                if self.type == self.TYPE_UDP:
                    if hasattr(self.sock, "recvfrom_into"):
                        n, addr = self.sock.recvfrom_into(self._buf)
                        self.target_addr = addr
                        raw = memoryview(self._buf)[:n]
                    else:
                        raw_bytes, addr = self.sock.recvfrom(recv_size)
                        self.target_addr = addr
                        n = len(raw_bytes)
                        if n:
                            self._buf[:n] = raw_bytes
                        raw = memoryview(self._buf)[:n]
                else:
                    if hasattr(self.sock, "recv_into"):
                        n = self.sock.recv_into(self._buf)
                    elif hasattr(self.sock, "readinto"):
                        n = self.sock.readinto(self._buf)
                    else:
                        raw_bytes = self.sock.recv(recv_size)
                        n = len(raw_bytes)
                        if n:
                            self._buf[:n] = raw_bytes
                    if n is None:
                        return
                    if n == 0:
                        self.connected = False
                        return
                    raw = memoryview(self._buf)[:n]

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
                # 自動餵入專屬 Parser
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
            return

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

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

    def __init__(self, bus_type=TYPE_WS, label="Bus", buf_size=None):
        self.type = bus_type
        self.label = label
        self.sock = None
        self.connected = False
        self.target_addr = None # UDP 發送對象
        
        # 內存隔離：每個 Bus 實例擁有獨立的緩衝區與解析器
        # 統一使用 Buffer.size 作為接收緩衝區大小
        if buf_size is None:
            buf_size = bus.shared.get('Buffer', {}).get('size', 4096)
        self._buf = bytearray(buf_size)
        self._ptr = 0

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

    def poll(self):
        if not self.connected or not self.sock: return
        self._ptr = 0

        try:
            if self.type == self.TYPE_UDP:
                if hasattr(self.sock, "recvfrom_into"):
                    n, addr = self.sock.recvfrom_into(self._buf)
                    self.target_addr = addr # 自動鎖定最後一個來源
                    raw = memoryview(self._buf)[:n]
                else:
                    raw_bytes, addr = self.sock.recvfrom(len(self._buf))
                    self.target_addr = addr
                    n = len(raw_bytes)
                    if n:
                        self._buf[:n] = raw_bytes
                    raw = memoryview(self._buf)[:n]
            else:
                n = self.sock.readinto(self._buf)
                if n is None:
                    return
                if n == 0:
                    self.connected = False
                    return
                raw = memoryview(self._buf)[:n]

            data = raw
            if self.type == self.TYPE_WS:
                off = 2
                pl_len = raw[1] & 0x7F
                if pl_len == 126: off = 4
                elif pl_len == 127: off = 10
                data = raw[off:]

            l = len(data)
            self._buf[:l] = data
            self._ptr = l

        except OSError:
            self._ptr = 0
            return

    def _send_all(self, data):
        if not self.connected or not self.sock or not data:
            return False
        mv = data if isinstance(data, memoryview) else memoryview(data)
        total = len(mv)
        pos = 0
        while pos < total:
            try:
                n = self.sock.send(mv[pos:])
                if n is None:
                    n = 0
                if n <= 0:
                    try:
                        time.sleep_ms(1)
                    except AttributeError:
                        time.sleep(0.001)
                    continue
                pos += n
            except OSError as e:
                if e.args and e.args[0] == 11:
                    try:
                        time.sleep_ms(1)
                    except AttributeError:
                        time.sleep(0.001)
                    continue
                self.connected = False
                return False
            except Exception:
                self.connected = False
                return False
        return True

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
                if not self._send_all(hdr):
                    return
                self._send_all(data)
            else:
                self._send_all(data)
        except:
            self.connected = False

    def any(self): return self._ptr

    def get_view(self):
        if not self._ptr:
            return None
        return memoryview(self._buf)[:self._ptr]

    def clear(self):
        self._ptr = 0
    
    def readinto(self, buf):
        ln = self._ptr
        buf[:ln] = self._buf[:ln]
        self._ptr = 0
        return ln

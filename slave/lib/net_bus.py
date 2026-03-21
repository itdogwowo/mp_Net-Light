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
        self._ws_buf = bytearray(buf_size + 14)
        self._ws_mv = memoryview(self._ws_buf)
        self._ws_start = 0
        self._ws_end = 0
        self._ws_need = 0
        self._ws_plen = 0
        self._ws_hlen = 0
        self._ws_masked = 0
        self._ws_mask0 = 0
        self._ws_mask1 = 0
        self._ws_mask2 = 0
        self._ws_mask3 = 0
        self._ws_poff = 0

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
            self._ws_start = 0
            self._ws_end = 0
            self._ws_need = 0
            self._ws_plen = 0
            self._ws_hlen = 0
            self._ws_masked = 0
            print(f"🔌 [{self.label}] Connection Closed.")

    def _ws_feed(self, data):
        if not data:
            return
        ln = len(data)
        cap = len(self._ws_buf)
        if ln > cap:
            self._ws_start = 0
            self._ws_end = 0
            self._ws_need = 0
            return

        free = cap - self._ws_end
        if free < ln and self._ws_start:
            keep = self._ws_end - self._ws_start
            if keep:
                self._ws_mv[:keep] = self._ws_mv[self._ws_start:self._ws_end]
            self._ws_start = 0
            self._ws_end = keep
            free = cap - self._ws_end

        if free < ln:
            self._ws_start = 0
            self._ws_end = 0
            self._ws_need = 0
            return

        self._ws_mv[self._ws_end:self._ws_end + ln] = data
        self._ws_end += ln

    def _ws_deframe_to_out(self):
        out = self._buf
        out_cap = len(out)
        out_pos = 0

        while out_pos < out_cap:
            avail = self._ws_end - self._ws_start
            if self._ws_need and avail < self._ws_need:
                break

            if self._ws_need == 0:
                if avail < 2:
                    break
                b0 = self._ws_buf[self._ws_start]
                b1 = self._ws_buf[self._ws_start + 1]
                plen = b1 & 0x7F
                masked = 1 if (b1 & 0x80) else 0
                hlen = 2
                if plen == 126:
                    if avail < 4:
                        break
                    plen = struct.unpack_from(">H", self._ws_buf, self._ws_start + 2)[0]
                    hlen = 4
                elif plen == 127:
                    if avail < 10:
                        break
                    plen = struct.unpack_from(">Q", self._ws_buf, self._ws_start + 2)[0]
                    hlen = 10
                if masked:
                    if avail < hlen + 4:
                        break
                    mpos = self._ws_start + hlen
                    self._ws_mask0 = self._ws_buf[mpos]
                    self._ws_mask1 = self._ws_buf[mpos + 1]
                    self._ws_mask2 = self._ws_buf[mpos + 2]
                    self._ws_mask3 = self._ws_buf[mpos + 3]
                    hlen += 4

                opcode = b0 & 0x0F
                if opcode == 8:
                    self.connected = False
                    return 0
                if opcode in (9, 10):
                    self._ws_start += hlen + plen
                    if self._ws_start >= self._ws_end:
                        self._ws_start = 0
                        self._ws_end = 0
                    continue

                self._ws_plen = plen
                self._ws_hlen = hlen
                self._ws_masked = masked
                self._ws_poff = 0
                self._ws_need = hlen + plen

            avail = self._ws_end - self._ws_start
            if avail < self._ws_need:
                break

            payload_pos = self._ws_start + self._ws_hlen + self._ws_poff
            remain = self._ws_plen - self._ws_poff
            space = out_cap - out_pos
            take = remain if remain < space else space

            if self._ws_masked:
                for i in range(take):
                    mi = (self._ws_poff + i) & 3
                    m = self._ws_mask0 if mi == 0 else self._ws_mask1 if mi == 1 else self._ws_mask2 if mi == 2 else self._ws_mask3
                    out[out_pos + i] = self._ws_buf[payload_pos + i] ^ m
            else:
                out[out_pos:out_pos + take] = self._ws_buf[payload_pos:payload_pos + take]

            out_pos += take
            self._ws_poff += take

            if self._ws_poff >= self._ws_plen:
                self._ws_start += self._ws_hlen + self._ws_plen
                if self._ws_start >= self._ws_end:
                    self._ws_start = 0
                    self._ws_end = 0
                self._ws_need = 0
                self._ws_plen = 0
                self._ws_hlen = 0
                self._ws_masked = 0
                self._ws_poff = 0

        self._ptr = out_pos
        return out_pos

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
                if self.type == self.TYPE_WS:
                    self._ws_feed(memoryview(self._buf)[:n])
                    self._ws_deframe_to_out()
                else:
                    self._ptr = n

        except OSError:
            self._ptr = 0
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

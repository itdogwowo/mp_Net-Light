# slave_controller/lib/proto.py
"""
Python 版本的 CMD 封包協議
移植自 MicroPython /lib/proto.py
"""
import struct

SOF = b"NL"
CUR_VER = 3
ADDR_BROADCAST = 0xFFFF

HDR_FMT = "<2sBHHH"
HDR_LEN = struct.calcsize(HDR_FMT)  # 11 bytes
CRC_FMT = "<H"
CRC_LEN = 2
MAX_LEN_DEFAULT = 4096

# CRC16-CCITT-FALSE lookup table
_CRC16_TAB = None

def _crc16_init_table():
    """初始化 CRC16 查找表"""
    global _CRC16_TAB
    tab = [0] * 256
    poly = 0x1021
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        tab[i] = crc
    _CRC16_TAB = tab

def crc16_ccitt(data: bytes, init=0xFFFF) -> int:
    """計算 CRC16-CCITT-FALSE"""
    global _CRC16_TAB
    if _CRC16_TAB is None:
        _crc16_init_table()
    
    crc = init & 0xFFFF
    for b in data:
        crc = ((crc << 8) ^ _CRC16_TAB[((crc >> 8) ^ b) & 0xFF]) & 0xFFFF
    return crc

def pack_packet(cmd: int, payload: bytes = b"", addr: int = ADDR_BROADCAST, ver: int = CUR_VER) -> bytes:
    """
    打包 CMD 封包
    格式: SOF(2) VER(1) ADDR(2) CMD(2) LEN(2) DATA CRC16(2)
    """
    if payload is None:
        payload = b""
    
    ln = len(payload)
    header = struct.pack(HDR_FMT, SOF, ver & 0xFF, addr & 0xFFFF, cmd & 0xFFFF, ln & 0xFFFF)
    
    # CRC 覆蓋 VER..DATA (不含 SOF)
    crc = crc16_ccitt(header[2:] + payload)
    
    return header + payload + struct.pack(CRC_FMT, crc)

class StreamParser:
    """
    流式封包解析器 (TCP/黏包處理)
    """
    def __init__(self, max_len=MAX_LEN_DEFAULT, accept_addr=None):
        self.max_len = max_len
        self.accept_addr = accept_addr
        self.buf = bytearray()
        self.drop_bytes = 0
    
    def feed(self, data: bytes):
        """餵入數據"""
        if data:
            self.buf.extend(data)
    
    def _shrink_front(self, n: int):
        """丟棄前 n 字節"""
        if n <= 0:
            return
        if n >= len(self.buf):
            self.buf = bytearray()
        else:
            self.buf = self.buf[n:]
    
    def _shrink_keep_last(self, n_last: int):
        """只保留最後 n_last 字節"""
        if n_last <= 0:
            self.drop_bytes += len(self.buf)
            self.buf = bytearray()
            return
        if len(self.buf) > n_last:
            self.drop_bytes += (len(self.buf) - n_last)
            self.buf = self.buf[-n_last:]
    
    def _resync_to_sof(self) -> bool:
        """重新同步到 SOF"""
        if len(self.buf) < 2:
            return False
        
        idx = self.buf.find(SOF)
        if idx < 0:
            self._shrink_keep_last(1)
            return False
        
        if idx > 0:
            self.drop_bytes += idx
            self._shrink_front(idx)
        
        return len(self.buf) >= HDR_LEN
    
    def _addr_ok(self, addr: int) -> bool:
        """檢查地址是否接受"""
        if self.accept_addr is None:
            return True
        return (addr == self.accept_addr) or (addr == ADDR_BROADCAST)
    
    def pop(self):
        """
        彈出一個完整封包
        yield (ver, addr, cmd, payload)
        """
        while True:
            # 重新同步到 SOF
            if not self._resync_to_sof():
                return
            
            if len(self.buf) < HDR_LEN:
                return
            
            # 解析 header
            sof, ver, addr, cmd, ln = struct.unpack_from(HDR_FMT, self.buf, 0)
            
            # 驗證 header
            if sof != SOF or ver != CUR_VER or ln > self.max_len:
                self.drop_bytes += 1
                self._shrink_front(1)
                continue
            
            # 檢查是否收齊完整幀
            frame_len = HDR_LEN + ln + CRC_LEN
            if len(self.buf) < frame_len:
                return
            
            # 提取 payload 和 CRC
            payload = bytes(self.buf[HDR_LEN:HDR_LEN + ln])
            crc_recv = struct.unpack_from(CRC_FMT, self.buf, HDR_LEN + ln)[0]
            
            # 驗證 CRC
            crc_calc = crc16_ccitt(bytes(self.buf[2:HDR_LEN]) + payload)
            if crc_recv != crc_calc:
                print(f"[Proto] CRC 錯誤: recv=0x{crc_recv:04X}, calc=0x{crc_calc:04X}")
                self.drop_bytes += 1
                self._shrink_front(1)
                continue
            
            # 丟棄已處理的幀
            self._shrink_front(frame_len)
            
            # 檢查地址
            if not self._addr_ok(addr):
                continue
            
            yield ver, addr, cmd, payload
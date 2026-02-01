import struct

# --- 跨平台兼容墊片 (PC 與 MicroPython 共享) ---
import sys

# 檢測是否為 MicroPython
IS_MICROPYTHON = (sys.implementation.name == 'micropython')

if not IS_MICROPYTHON:
    # 這裡是 PC (Standard Python) 環境
    # 定義模擬的 MicroPython 裝飾器
    class micropython:
        @staticmethod
        def viper(f): return f
        @staticmethod
        def native(f): return f
    
    # 定義模擬的 Viper 類型關鍵字，防止 NameError
    ptr8 = bytes
    ptr16 = bytes
    int32 = int
    uint16 = int
else:
    # 這裡是 MicroPython 環境
    import micropython

# --- 協議常量 ---
SOF = b"NL"
CUR_VER = 3
ADDR_BROADCAST = 0xFFFF
MAX_LEN_DEFAULT = 8192

HDR_FMT = "<2sBHHH"
HDR_LEN = 9 # struct.calcsize(HDR_FMT)
CRC_FMT = "<H"
CRC_LEN = 2

class Proto:
    @micropython.viper
    def crc16(data: ptr8, length: int) -> int:
        """高性能 CRC16 內核"""
        crc: int = 0xFFFF
        for i in range(length):
            crc ^= data[i] << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    @staticmethod
    def pack(cmd: int, payload: bytes = b"", addr: int = ADDR_BROADCAST) -> bytes:
        if payload is None: payload = b""
        ln = len(payload)
        header = struct.pack(HDR_FMT, SOF, CUR_VER, addr, cmd, ln)
        crc_data = header[2:] + payload
        # 注意：在 PC 上傳入內容給 Viper (crc16) 函數也是沒問題的
        crc_val = Proto.crc16(crc_data, len(crc_data))
        return header + payload + struct.pack(CRC_FMT, crc_val)

class StreamParser:
    def __init__(self, max_len=MAX_LEN_DEFAULT):
        self.max_len = max_len
        self.buf = bytearray()
        
    def feed(self, data: bytes):
        if data: self.buf.extend(data)

    def pop(self):
        # 這裡直接使用 HDR_LEN
        while len(self.buf) >= HDR_LEN:
            idx = self.buf.find(SOF)
            if idx < 0:
                self.buf = bytearray()
                return
            if idx > 0:
                self.buf = self.buf[idx:]
            
            if len(self.buf) < HDR_LEN: return
            
            # 使用 struct.unpack 替代 Struct.unpack_from
            hdr = struct.unpack(HDR_FMT, self.buf[:HDR_LEN])
            sof, ver, addr, cmd, ln = hdr
            
            if ver != CUR_VER or ln > self.max_len:
                self.buf = self.buf[1:]
                continue
                
            total_len = HDR_LEN + ln + CRC_LEN
            if len(self.buf) < total_len: return
            
            payload = self.buf[HDR_LEN : HDR_LEN + ln]
            # 獲取最後兩個字節作為 CRC
            crc_received = struct.unpack(CRC_FMT, self.buf[HDR_LEN + ln : total_len])[0]
            
            calc_area = self.buf[2 : HDR_LEN + ln]
            if Proto.crc16(calc_area, len(calc_area)) == crc_received:
                self.buf = self.buf[total_len:]
                yield ver, addr, cmd, bytes(payload)
            else:
                self.buf = self.buf[1:]
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
        self._buf = bytearray(max_len + HDR_LEN + CRC_LEN)
        self._mv = memoryview(self._buf)
        self._start = 0
        self._end = 0
        
    def feed(self, data):
        if not data:
            return
        ln = len(data)
        cap = len(self._buf)
        if ln > cap:
            self._start = 0
            self._end = 0
            return

        free = cap - self._end
        if free < ln and self._start:
            keep = self._end - self._start
            if keep:
                self._mv[:keep] = self._mv[self._start:self._end]
            self._start = 0
            self._end = keep
            free = cap - self._end

        if free < ln:
            self._start = 0
            self._end = 0
            return

        self._mv[self._end:self._end + ln] = data
        self._end += ln

    def pop(self):
        while (self._end - self._start) >= HDR_LEN:
            idx = self._buf.find(SOF, self._start, self._end)
            if idx < 0:
                self._start = 0
                self._end = 0
                return

            if idx != self._start:
                self._start = idx
                if (self._end - self._start) < HDR_LEN:
                    return

            sof, ver, addr, cmd, ln = struct.unpack_from(HDR_FMT, self._buf, self._start)

            if ver != CUR_VER or ln > self.max_len:
                self._start += 1
                continue

            total_len = HDR_LEN + ln + CRC_LEN
            if (self._end - self._start) < total_len:
                return

            payload_start = self._start + HDR_LEN
            payload_end = payload_start + ln
            crc_received = struct.unpack_from(CRC_FMT, self._buf, payload_end)[0]

            calc_area = self._mv[self._start + 2 : payload_end]
            if Proto.crc16(calc_area, len(calc_area)) == crc_received:
                payload = self._mv[payload_start:payload_end]
                self._start += total_len
                if self._start == self._end:
                    self._start = 0
                    self._end = 0
                yield ver, addr, cmd, payload
            else:
                self._start += 1

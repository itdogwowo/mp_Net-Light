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
    @staticmethod
    def crc16(data, length: int) -> int:
        """高性能 CRC16 內核 (兼容 bytes 和 memoryview)"""
        crc: int = 0xFFFF
        # 在 MicroPython 中，如果 data 是 memoryview，可以直接索引
        # 但如果是 slice，viper 可能不支持。
        # 為了安全起見，這裡使用標準 Python 寫法，依賴 @micropython.native 加速
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
    """
    高性能流解析器 (Zero-Copy Ring Buffer 變體)
    使用固定大小的 buffer + memoryview，避免內存分配
    """
    def __init__(self, max_len=MAX_LEN_DEFAULT):
        self.max_len = max_len
        # 預分配緩衝區：HDR + Payload + CRC
        # 為了處理粘包，緩衝區稍微大一點
        self.buf_size = max_len * 2
        self.buf = bytearray(self.buf_size)
        self.view = memoryview(self.buf)
        self.w_ptr = 0 # 寫入指針 (有效數據結尾)
        self.r_ptr = 0 # 讀取指針 (有效數據開頭)
        
    def feed(self, data):
        """接收數據 (bytes 或 memoryview)"""
        if not data: return
        
        l = len(data)
        # 檢查緩衝區剩餘空間
        if self.w_ptr + l > self.buf_size:
            # 空間不足，進行內存整理 (Compact)
            # 將未處理的數據搬移到開頭
            remaining = self.w_ptr - self.r_ptr
            if remaining > 0:
                self.buf[:remaining] = self.view[self.r_ptr : self.w_ptr]
            
            self.r_ptr = 0
            self.w_ptr = remaining
            
            # 如果整理後還是不夠 (數據包太大)，則擴容或丟棄
            if self.w_ptr + l > self.buf_size:
                # 簡單策略：丟棄舊數據或擴容 (這裡選擇報錯/丟棄，假設 max_len 足夠)
                # print("Buffer overflow in Parser")
                return 

        # 寫入數據
        self.buf[self.w_ptr : self.w_ptr + l] = data
        self.w_ptr += l

    def pop(self):
        """嘗試解析封包 (Generator)"""
        while True:
            # 計算有效數據長度
            valid_len = self.w_ptr - self.r_ptr
            if valid_len < HDR_LEN:
                return # 數據不足 Header

            # 尋找 SOF (0x4E 0x4C)
            # 在有效窗口內搜索
            # 注意：MicroPython bytearray.find 可能不支持 start/end 參數，需確認
            # 這裡我們使用 view 切片搜索
            window = self.view[self.r_ptr : self.w_ptr]
            
            # 優化：如果第一個字節就是 'N'，可能就是 SOF
            if window[0] == 0x4E and valid_len >= 2 and window[1] == 0x4C:
                idx = 0
            else:
                # 否則搜索
                # 轉換為 bytes 搜索可能比較慢，但為了兼容性
                # 如果是 micropython，直接 bytearray 切片搜索是高效的
                try:
                    # 在 window 中搜索 SOF
                    # 注意：window 是 memoryview，find 方法可能不存在
                    # 需要轉為 bytes 嗎？這會拷貝。
                    # 手動搜索？
                    # 簡單優化：直接遍歷
                    found = False
                    for i in range(valid_len - 1):
                        if self.buf[self.r_ptr + i] == 0x4E and self.buf[self.r_ptr + i + 1] == 0x4C:
                            idx = i
                            found = True
                            break
                    
                    if not found:
                        # 整個窗口都沒有 SOF，丟棄除最後一個字節外的所有數據 (防止切斷 SOF)
                        self.r_ptr = self.w_ptr - 1
                        return
                except:
                    return

            # 如果 SOF 不在開頭，丟棄前面的垃圾數據
            if idx > 0:
                self.r_ptr += idx
                valid_len -= idx
            
            # 再次檢查長度
            if valid_len < HDR_LEN: return
            
            # 解析 Header
            # struct.unpack_from 支持 buffer protocol
            try:
                hdr = struct.unpack_from(HDR_FMT, self.buf, self.r_ptr)
                sof, ver, addr, cmd, ln = hdr
            except:
                # 解析失敗？跳過 SOF
                self.r_ptr += 2
                continue
            
            # 檢查版本和長度
            if ver != CUR_VER or ln > self.max_len:
                # 無效 Header，跳過 SOF
                self.r_ptr += 2
                continue
                
            total_len = HDR_LEN + ln + CRC_LEN
            if valid_len < total_len: return # 數據不足完整包
            
            # 完整包已就緒！
            # 1. 校驗 CRC
            # CRC 區域：Header[2:] (從 ADDR 開始) + Payload
            # self.buf[self.r_ptr + 2 : self.r_ptr + HDR_LEN + ln]
            calc_start = self.r_ptr + 2
            calc_end = self.r_ptr + HDR_LEN + ln
            
            # 獲取接收到的 CRC
            crc_pos = calc_end
            crc_received = (self.buf[crc_pos] | (self.buf[crc_pos+1] << 8))
            
            # 計算 CRC (使用切片傳入，Proto.crc16 需支持)
            # 注意：這裡切片如果是 memoryview，不會拷貝
            calc_view = self.view[calc_start : calc_end]
            if Proto.crc16(calc_view, len(calc_view)) == crc_received:
                # ✅ 校驗通過
                # 提取 Payload (返回 bytes 以便後續處理，這裡無法避免一次拷貝給上層)
                # 除非上層支持 memoryview。為了兼容性，這裡轉 bytes
                payload = bytes(self.view[self.r_ptr + HDR_LEN : self.r_ptr + HDR_LEN + ln])
                
                # 移動讀指針
                self.r_ptr += total_len
                
                yield ver, addr, cmd, payload
            else:
                # ❌ 校驗失敗，跳過 SOF，繼續尋找
                # print(f"CRC Fail: {cmd:04X}")
                self.r_ptr += 2
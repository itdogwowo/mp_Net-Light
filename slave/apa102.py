import machine
import time

class APA102:
    """
    APA102 ESP32-P4 極速版 - 雙緩衝 + Viper 內核
    專為追求極致性能、零內存碎片、高刷新率設計
    """
    def __init__(self, num_leds, spi_id=1, sck_pin=8, mosi_pin=7, baudrate=8_000_000):
        self.num_leds = num_leds
        self.buf_length = num_leds * 4
        
        # 初始化 SPI
        self.spi = machine.SPI(
            spi_id,
            baudrate=baudrate,
            polarity=1,
            phase=1,
            sck=machine.Pin(sck_pin),
            mosi=machine.Pin(mosi_pin)
        )
        
        # 1. 原始數據接收區 (用於 readinto)
        self.raw_buffer = bytearray(self.buf_length)
        
        # 2. SPI 傳輸專用區 (APA102 原生格式)
        self.spi_buffer = bytearray(self.buf_length)
        
        # 3. 協議控制幀
        self.start_frame = bytearray([0x00, 0x00, 0x00, 0x00])
        # 長度計算：至少 n/16 bytes
        end_len = max(4, (num_leds + 15) // 16)
        self.end_frame = bytearray([0xFF] * end_len)
        
        # 初始化標誌位
        self._init_spi_buffer()
        print(f"[APA102] 極速驅動初始化: {num_leds} LEDs, 使用雙緩衝策略")

    @micropython.viper
    def _init_spi_buffer(self):
        """初始化 spi_buffer 的亮度起始位 (0xE0)"""
        p_spi: ptr8 = ptr8(self.spi_buffer)
        for i in range(0, int(self.buf_length), 4):
            p_spi[i] = 0xE0

    @micropython.viper
    def _convert_fast(self):
        """
        終極 Viper 內核: 從 raw_buffer 讀取並寫入 spi_buffer
        [R, G, B, W] -> [0xE0|W, B, G, R]
        分離讀寫指針，最大化暫存器利用率
        """
        p_raw: ptr8 = ptr8(self.raw_buffer)
        p_spi: ptr8 = ptr8(self.spi_buffer)
        n: int = int(self.buf_length)
        
        for i in range(0, n, 4):
            # 一次性讀取到局部變量（暫存器）
            r = p_raw[i]
            g = p_raw[i + 1]
            b = p_raw[i + 2]
            w = p_raw[i + 3]
            
            # 轉換並寫入傳輸區
            p_spi[i]     = 0xE0 | (w >> 3) 
            p_spi[i + 1] = b
            p_spi[i + 2] = g
            p_spi[i + 3] = r

    def show(self):
        """執行轉換並發送數據"""
        self._convert_fast()
        self.spi.write(self.start_frame)
        self.spi.write(self.spi_buffer)
        self.spi.write(self.end_frame)

    def show_raw(self):
        """
        直接發送 raw_buffer (跳過轉換)
        前提是數據已經是 APA102 格式
        """
        self.spi.write(self.start_frame)
        self.spi.write(self.raw_buffer)
        self.spi.write(self.end_frame)

    def clear(self):
        """清空緩衝區"""
        # 這裡用 memoryview 填充可以更快，或者直接循環
        for i in range(self.buf_length):
            self.raw_buffer[i] = 0
        self._init_spi_buffer()

    def deinit(self):
        self.clear()
        self.show()
        time.sleep(0.01)
        self.spi.deinit()

# ==================== main.py 高性能集成用法 ====================
"""
# 實例化
apa = APA102(num_leds=336)

# 循環內
if is_streaming():
    # 🎯 絕招：直接讀入 raw_buffer，完全沒有內存分配開銷
    n = f_raw.readinto(apa.raw_buffer)
    
    if n < 1344: # 336*4
        f_raw.seek(0)
        f_raw.readinto(apa.raw_buffer)
    
    # 將 RGBW 轉換並輸出
    apa.show()
"""
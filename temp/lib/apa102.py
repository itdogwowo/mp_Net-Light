import machine
import micropython
import array
import time

class APA102:
    """
    APA102 極速驅動 - 專為 LEDcontroller 配套設計
    特性：雙緩衝、Viper 轉換、對齊 LEDcontroller 的 buf 操作
    """
    def __init__(self, num_leds, spi_id=1, sck_pin=8, mosi_pin=7, baudrate=8_000_000):
        self.n = num_leds
        self.buf_length = num_leds * 4
        
        # 1. 暴露給 LEDcontroller 的標準緩衝區 [G, R, B, W]
        # 注意：為了符合你 LEDcontroller 的 set_rgb 邏輯與 f.readinto 的性能
        self.buf = bytearray(self.buf_length)
        
        # 2. SPI 物理傳輸數據區 (原生 APA102 格式)
        self.spi_buffer = bytearray(self.buf_length)
        
        # 3. SPI 硬體初始化
        self.spi = machine.SPI(
            spi_id,
            baudrate=baudrate,
            polarity=1,
            phase=1,
            sck=machine.Pin(sck_pin),
            mosi=machine.Pin(mosi_pin)
        )
        
        # 協議控制幀
        self.start_frame = bytearray([0x00, 0x00, 0x00, 0x00])
        end_len = max(4, (num_leds + 15) // 16)
        self.end_frame = bytearray([0xFF] * end_len)
        
        self._init_spi_buffer()

    @micropython.viper
    def _init_spi_buffer(self):
        """初始化物理緩衝區的亮度標頭 0xE0"""
        p_spi: ptr8 = ptr8(self.spi_buffer)
        for i in range(0, int(self.buf_length), 4):
            p_spi[i] = 0xE0

    @micropython.viper
    def _convert(self):
        """
        Viper 內核：將 LEDcontroller 寫入的 [G, R, B, W] 轉換為 [0xE0|W, B, G, R]
        直接由 show() 調用
        """
        p_in: ptr8 = ptr8(self.buf)
        p_out: ptr8 = ptr8(self.spi_buffer)
        n: int = int(self.buf_length)
        
        for i in range(0, n, 4):
            # 讀取 LEDcontroller 規範的四字節 (假設最後一字節為亮度)
            g = p_in[i]
            r = p_in[i+1]
            b = p_in[i+2]
            w = p_in[i+3]
            
            # 寫入 APA102 格式 (亮度位 0xE0 + 5-bit)
            p_out[i]     = 0xE0 | (w >> 3) 
            p_out[i + 1] = b
            p_out[i + 2] = g
            p_out[i + 3] = r

    def show_raw(self):
        """
        🚀 快車道：零轉換直接輸出
        前提：self.buf 中的數據必須已經是 APA102 的硬體字節流
        """
        # 直接調用底層寫入，避開 Python 緩慢的 slice 操作
        self.spi.write(self.start_frame)
        self.spi.write(self.buf)
        self.spi.write(self.end_frame)
            
    def show(self):
        """物理輸出"""
        self._convert()
        self.show_raw()
        
    def write(self):
        """相容 LEDcontroller 的調用習慣"""
        self.show_raw()

    def fill(self, color):
        """相容 neopixel 接口"""
        g, r, b = color # 預設三元組
        for i in range(0, self.buf_length, 4):
            self.buf[i] = g
            self.buf[i+1] = r
            self.buf[i+2] = b
            self.buf[i+3] = 255 # 預設滿亮度
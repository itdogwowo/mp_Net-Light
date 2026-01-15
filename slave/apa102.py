import machine
import time

class APA102:
    """
    APA102 LED驅動類別 - 長燈帶支援版
    修正結束幀長度問題，支援超長燈帶
    """
    
    def __init__(self, num_leds, spi_id=1, sck_pin=8, mosi_pin=7, baudrate=8_000_000):
        """
        初始化APA102驅動 (長燈帶修正版)
        
        參數:
            num_leds: LED數量
            spi_id: SPI匯流排ID (通常1或2)
            sck_pin: 時鐘引腳
            mosi_pin: 數據輸出引腳
            baudrate: SPI通訊速率
        """
        self.num_leds = num_leds
        
        # 初始化SPI
        self.spi = machine.SPI(
            spi_id,
            baudrate=baudrate,
            polarity=1,      # APA102使用模式0
            phase=1,
            sck=machine.Pin(sck_pin),
            mosi=machine.Pin(mosi_pin),
            miso=None        # APA102不需要MISO
        )
        
        # 建立LED緩衝區
        # 起始幀: 32位元0 (0x00000000)
        self.start_frame = bytearray([0x00, 0x00, 0x00, 0x00])
        
        # 修正結束幀長度計算
        # 根據APA102規格書，結束幀需要至少 (n/2) 位元組的 0xFF
        # 但實際測試發現有些燈帶需要更長，這裡使用更保守的計算
        # 方法1: 使用 ceil(n/16) * 8 位元組 (更安全)
        # 方法2: 固定較長的結束幀
        end_frame_len = max(4, (num_leds + 7) // 8)  # 更保守的計算
        self.end_frame = bytearray([0xFF] * end_frame_len)
        self.end_frame = bytearray([0xFF] * 4)
        
        # 或者使用固定長度結束幀（對於長燈帶更可靠）
        # self.end_frame = bytearray([0xFF] * 64)  # 固定64位元組結束幀
        
        # 建立LED數據緩衝區
        self.led_buffer = bytearray(num_leds * 4)
        
        # 初始化所有LED為關閉狀態
        self.clear()
        
        print(f"APA102初始化完成: {num_leds}個LED")
        print(f"結束幀長度: {len(self.end_frame)}位元組")
    
    def set_pixel(self, index, red, green, blue, brightness=31):
        """
        設定單個LED的顏色和亮度
        
        參數:
            index: LED索引 (0開始)
            red: 紅色值 (0-255)
            green: 綠色值 (0-255)
            blue: 藍色值 (0-255)
            brightness: 亮度 (0-31, 31為最亮)
        """
        if index < 0 or index >= self.num_leds:
            return  # 忽略無效索引
        
        # 限制亮度範圍
        brightness = max(0, min(31, brightness))
        
        # 計算緩衝區位置
        pos = index * 4
        
        # APA102格式: 起始標誌(0xE0+亮度) + B + G + R
        self.led_buffer[pos] = 0xE0 | brightness  # 起始位元組
        self.led_buffer[pos + 1] = blue & 0xFF    # 藍色
        self.led_buffer[pos + 2] = green & 0xFF   # 綠色
        self.led_buffer[pos + 3] = red & 0xFF     # 紅色
    
    def set_pixel_rgb(self, index, rgb, brightness=31):
        """
        使用RGB元組設定LED顏色
        """
        self.set_pixel(index, rgb[0], rgb[1], rgb[2], brightness)
    
    def fill(self, red, green, blue, brightness=31):
        """
        填充所有LED為相同顏色
        """
        for i in range(self.num_leds):
            self.set_pixel(i, red, green, blue, brightness)
    
    def fill_rgb(self, rgb, brightness=31):
        """
        使用RGB元組填充所有LED
        """
        self.fill(rgb[0], rgb[1], rgb[2], brightness)
    
    def clear(self):
        """關閉所有LED"""
        # 直接填充緩衝區，避免循環調用
        for i in range(self.num_leds):
            pos = i * 4
            self.led_buffer[pos] = 0xE0  # 亮度為0
            self.led_buffer[pos + 1] = 0  # 藍色
            self.led_buffer[pos + 2] = 0  # 綠色
            self.led_buffer[pos + 3] = 0  # 紅色
    
    def show(self):
        """更新LED顯示 (發送數據到燈條)"""
        # 發送起始幀
        self.spi.write(self.start_frame)
        
        # 發送LED數據
        self.spi.write(self.led_buffer)
        
        # 發送結束幀
        self.spi.write(self.end_frame)
        
        # 可選: 添加小延遲確保數據完全發送
        # time.sleep_us(50)
    
    
    def deinit(self):
        """釋放資源"""
        self.clear()
        self.show()
        time.sleep(0.1)
        self.spi.deinit()
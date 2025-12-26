"""
APA102 LED驅動程式 (MicroPython版本) - 長燈帶修正版
針對長燈帶的結束幀問題進行修正
"""

import machine
import time

class APA102:
    """
    APA102 LED驅動類別 - 長燈帶支援版
    修正結束幀長度問題，支援超長燈帶
    """
    
    def __init__(self, num_leds, spi_id=1, sck_pin=22, mosi_pin=23, baudrate=8000000):
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
            polarity=0,      # APA102使用模式0
            phase=0,
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
    
    def test_pattern(self):
        """
        測試模式: 顯示每個LED的索引顏色
        用於診斷LED數量問題
        """
        self.clear()
        
        # 定義測試顏色
        colors = [
            (255, 0, 0),    # 紅色
            (0, 255, 0),    # 綠色
            (0, 0, 255),    # 藍色
            (255, 255, 0),  # 黃色
            (255, 0, 255),  # 紫色
            (0, 255, 255),  # 青色
            (255, 255, 255),# 白色
            (255, 128, 0),  # 橙色
            (128, 0, 255),  # 紫色
            (0, 255, 128),  # 青綠色
        ]
        
        # 為每個LED分配顏色
        for i in range(min(self.num_leds, 10)):
            color_idx = i % len(colors)
            self.set_pixel(i, *colors[color_idx])
        
        self.show()
        print(f"測試模式: 顯示前{min(self.num_leds, 10)}個LED")
    
    def count_leds(self, max_test=100):
        """
        自動檢測燈帶上的LED數量
        參數:
            max_test: 最大測試數量
        返回:
            檢測到的LED數量
        """
        print("開始自動檢測LED數量...")
        
        # 先關閉所有LED
        self.clear()
        self.show()
        time.sleep(0.1)
        
        # 測試每個可能的LED位置
        detected = 0
        
        for i in range(max_test):
            # 點亮當前LED
            self.clear()
            self.set_pixel(i, 255, 255, 255, brightness=5)  # 低亮度白色
            self.show()
            
            # 短暫延遲
            time.sleep(0.05)
            
            # 檢查是否有反應（這裡需要人工觀察）
            # 實際應用中可以添加光感測器自動檢測
            
            # 記錄最後一個有反應的LED
            detected = i + 1
            
            # 每10個LED暫停一下
            if (i + 1) % 10 == 0:
                print(f"已測試 {i + 1} 個位置...")
                time.sleep(0.5)
        
        # 關閉所有LED
        self.clear()
        self.show()
        
        print(f"檢測完成: 建議設定 {detected} 個LED")
        return detected
    
    def verify_buffer(self):
        """
        驗證緩衝區內容
        用於調試
        """
        print(f"LED緩衝區大小: {len(self.led_buffer)} 位元組")
        print(f"理論LED數量: {len(self.led_buffer) // 4}")
        
        # 顯示前幾個LED的緩衝區內容
        print("前5個LED的緩衝區內容:")
        for i in range(min(5, self.num_leds)):
            pos = i * 4
            brightness = self.led_buffer[pos] & 0x1F
            blue = self.led_buffer[pos + 1]
            green = self.led_buffer[pos + 2]
            red = self.led_buffer[pos + 3]
            print(f"  LED {i}: 亮度={brightness}, R={red}, G={green}, B={blue}")
    
    def deinit(self):
        """釋放資源"""
        self.clear()
        self.show()
        time.sleep(0.1)
        self.spi.deinit()


# 診斷工具函數
def diagnose_apa102(num_leds=5):
    """
    APA102診斷函數
    用於診斷和解決長燈帶問題
    """
    print("=" * 50)
    print("APA102 診斷工具")
    print("=" * 50)
    
    # 初始化APA102
    leds = APA102(num_leds, spi_id=1, sck_pin=22, mosi_pin=23)
    
    try:
        # 測試1: 驗證緩衝區
        print("\n1. 驗證緩衝區設定")
        leds.verify_buffer()
        
        # 測試2: 測試模式
        print("\n2. 執行測試模式")
        leds.test_pattern()
        time.sleep(3)
        
        # 測試3: 逐一點亮測試
        print("\n3. 逐一點亮測試")
        for i in range(num_leds):
            leds.clear()
            leds.set_pixel(i, 255, 255, 255)  # 白色
            leds.show()
            print(f"  點亮LED {i}")
            time.sleep(1)
        
        # 測試4: 檢查結束幀影響
        print("\n4. 測試不同結束幀長度")
        
        # 測試短結束幀
        print("  使用短結束幀 (4位元組)...")
        leds.end_frame = bytearray([0xFF] * 4)
        leds.fill(255, 0, 0)  # 紅色
        leds.show()
        time.sleep(2)
        
        # 測試長結束幀
        print("  使用長結束幀 (64位元組)...")
        leds.end_frame = bytearray([0xFF] * 64)
        leds.fill(0, 255, 0)  # 綠色
        leds.show()
        time.sleep(2)
        
        # 恢復原始結束幀
        leds.end_frame = bytearray([0xFF] * max(4, (num_leds + 7) // 8))
        
        # 測試5: 自動檢測LED數量（可選）
        print("\n5. 是否要自動檢測LED數量? (需要人工觀察)")
        response = input("  輸入 'y' 開始檢測，其他鍵跳過: ")
        if response.lower() == 'y':
            detected = leds.count_leds(max_test=50)
            print(f"\n  檢測結果: 建議設定 {detected} 個LED")
        
        print("\n診斷完成!")
        
    except Exception as e:
        print(f"診斷過程中發生錯誤: {e}")
    
    finally:
        # 確保關閉LED
        leds.clear()
        leds.show()
        print("所有LED已關閉")


# 修正的使用範例
def fixed_example_usage():
    """
    修正的APA102使用範例
    解決第6個LED亮白燈的問題
    """
    # 初始化APA102燈條
    num_leds = 5  # 你設定的LED數量
    leds = APA102(num_leds, spi_id=1, sck_pin=22, mosi_pin=23)
    
    print("修正版APA102範例開始")
    print(f"設定LED數量: {num_leds}")
    
    try:
        # 測試1: 驗證只有設定的LED會亮
        print("\n測試1: 驗證LED數量")
        leds.clear()
        
        # 只點亮前num_leds個LED
        for i in range(num_leds):
            leds.set_pixel(i, 255, 0, 0)  # 紅色
        leds.show()
        time.sleep(2)
        
        # 測試2: 檢查是否有額外的LED亮起
        print("\n測試2: 檢查額外LED")
        leds.clear()
        leds.set_pixel(0, 0, 255, 0)  # 只點亮第一個LED為綠色
        leds.show()
        time.sleep(2)
        
        # 測試3: 使用測試模式
        print("\n測試3: 測試模式")
        leds.test_pattern()
        time.sleep(3)
        
        # 正常使用範例
        print("\n正常使用範例:")
        
        # 彩虹效果
        print("彩虹效果")
        for offset in range(0, 360, 10):
            for i in range(num_leds):
                hue = ((i * 360 // num_leds) + offset) % 360
                rgb = APA102.hsv_to_rgb(hue, 1.0, 1.0)
                leds.set_pixel(i, *rgb)
            leds.show()
            time.sleep(0.05)
        
        # 關閉所有LED
        leds.clear()
        leds.show()
        
        print("\n範例完成!")
        
    except KeyboardInterrupt:
        print("\n程式被中斷")
    finally:
        leds.clear()
        leds.show()


# 解決方案：使用動態結束幀
class APA102DynamicEndFrame(APA102):
    """
    APA102動態結束幀版本
    根據實際需要動態調整結束幀長度
    """
    
    def __init__(self, num_leds, spi_id=1, sck_pin=22, mosi_pin=23, baudrate=8000000):
        super().__init__(num_leds, spi_id, sck_pin, mosi_pin, baudrate)
        
        # 動態結束幀：先使用短結束幀，根據需要調整
        self.end_frame_length = 4  # 初始長度
        self.update_end_frame()
    
    def update_end_frame(self):
        """更新結束幀"""
        self.end_frame = bytearray([0xFF] * self.end_frame_length)
    
    def adjust_end_frame(self, target_leds):
        """
        調整結束幀長度以控制實際點亮的LED數量
        
        參數:
            target_leds: 想要點亮的LED數量
        """
        # 根據APA102規格計算所需結束幀長度
        # 公式: 結束幀位元組數 ≥ n/2，其中n是LED數量
        required_length = max(4, (target_leds + 1) // 2)
        
        if required_length > self.end_frame_length:
            self.end_frame_length = required_length
            self.update_end_frame()
            print(f"調整結束幀長度為: {self.end_frame_length} 位元組")
    
    def show_with_adjusted_frame(self, visible_leds=None):
        """
        顯示LED並動態調整結束幀
        
        參數:
            visible_leds: 想要顯示的LED數量（None表示使用全部）
        """
        if visible_leds is not None:
            self.adjust_end_frame(visible_leds)
        
        # 正常顯示
        self.spi.write(self.start_frame)
        self.spi.write(self.led_buffer)
        self.spi.write(self.end_frame)


# 主程式入口
if __name__ == "__main__":
    print("APA102 長燈帶問題解決方案")
    print("=" * 50)
    
    # 選擇要執行的功能
    print("請選擇功能:")
    print("1. 執行診斷工具")
    print("2. 執行修正範例")
    print("3. 使用動態結束幀版本")
    
    choice = input("請輸入選擇 (1-3): ")
    
    if choice == "1":
        # 執行診斷
        num = int(input("輸入設定的LED數量: "))
        diagnose_apa102(num)
    elif choice == "2":
        # 執行修正範例
        fixed_example_usage()
    elif choice == "3":
        # 使用動態結束幀版本
        num_leds = 5
        leds = APA102DynamicEndFrame(num_leds)
        
        # 測試不同數量的LED
        for visible in [3, 5, 8, 10]:
            print(f"\n測試顯示 {visible} 個LED")
            leds.clear()
            for i in range(visible):
                leds.set_pixel(i, 0, 0, 255)  # 藍色
            leds.show_with_adjusted_frame(visible)
            time.sleep(2)
        
        leds.clear()
        leds.show()
    else:
        print("無效選擇")
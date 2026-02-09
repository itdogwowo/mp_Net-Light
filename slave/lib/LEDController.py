from machine import Timer, I2C, SoftI2C, ADC, Pin, PWM, UART
import esp, gc, time, json, utime, array, struct, ubinascii, _thread, micropython

C_LUMN = 1.0


class LEDcontroller:
    '''
    LED控制器 - 流式傳輸專用版 (0-4095範圍) + 多色序支持
    
    led_IO = {
        'led_IO': led對象 (neopixel/APA102/PCA9685), 
        'Q': led數量, 
        'order': 'GRB' (可選, 支持 RGB/GRB/RGBW/GRBW 等)
    }
    
    支持的 LED 類型:
    - 'RGB': WS2812/SK6812 (NeoPixel)
    - 'APA102': APA102/SK9822 (SPI)
    - 'i2c_LED': PCA9685 (I2C PWM)
    
    核心功能:
    - st_init(): 初始化流式緩衝區
    - st_load_from_buffer(source, offset): 從大緩衝區加載一幀
    - st_show(): 渲染到硬體
    - st_close(): 關閉流式模式
    
    性能:
    - 單像素轉換: 3.4 μs
    - 1000像素: 3.4 ms
    - 零拷貝切片操作
    '''
    
    def __init__(self, led_Type, led_IO):
        self.led_Type = led_Type
        self.led_IO = led_IO
        
        # ========================================
        # 色序處理 (支持 RGB/GRB/RGBW/WBGR 等)
        # ========================================
        self.order = led_IO.get('order', 'GRB').upper()
        self.bpp = len(self.order)  # Bytes Per Pixel (3 或 4)
        
        # 計算 R/G/B/W 在緩衝區中的偏移量
        self._r_off, self._g_off, self._b_off, self._w_off = self._get_order_offsets(self.order)
        
        # ========================================
        # 流式傳輸核心
        # ========================================
        self.streaming_mode = False
        self.st_buff = None  # 流式緩衝區 (僅在 st_init 後啟用)
        self.frame_size = 0  # 單幀大小 (字節)
        
        self.setup()
    
    # ========================================
    # 色序偏移量計算
    # ========================================
    def _get_order_offsets(self, order):
        """
        計算 R/G/B/W 在緩衝區中的偏移量
        
        參數:
            order: 色序字符串 (例如 'GRB', 'RGBW', 'WBGR')
        
        返回:
            (r_off, g_off, b_off, w_off) - 每個顏色的索引位置
        """
        r_off = order.find('R') if 'R' in order else -1
        g_off = order.find('G') if 'G' in order else -1
        b_off = order.find('B') if 'B' in order else -1
        w_off = order.find('W') if 'W' in order else -1
        
        return r_off, g_off, b_off, w_off
    
    # ========================================
    # 魔術方法 (支持序列操作)
    # ========================================
    @micropython.native
    def __len__(self):
        """支援 len() 操作,返回 LED 總數"""
        return self.led_IO['Q']
    
    @micropython.native
    def __getitem__(self, index):
        """支持 led[i] 訪問"""
        if isinstance(index, slice):
            return [self.LED(self, i) for i in range(self.led_IO['Q'])[index]]
        elif isinstance(index, int):
            if -self.led_IO['Q'] <= index < self.led_IO['Q']:
                actual_index = index if index >= 0 else self.led_IO['Q'] + index
                return self.LED(self, actual_index)
            else:
                raise IndexError('Index out of range')
        else:
            raise TypeError("Invalid index type")
    
    @micropython.native
    def __iter__(self):
        """支持 for led in controller 迭代"""
        return (self.LED(self, i) for i in range(self.led_IO['Q']))
    
    # ========================================
    # 內部 LED 類 (簡化版)
    # ========================================
    class LED:
        """單個 LED 訪問器 (用於未來擴展)"""
        def __init__(self, controller, index):
            self.controller = controller
            self.index = index
        
        @micropython.viper
        def get_pixel_offset(self) -> int:
            """獲取該 LED 在緩衝區中的起始位置"""
            return int(self.index) * int(self.controller.bpp)
    
    # ========================================
    # 硬體設定
    # ========================================
    def setup(self):
        """初始化硬體設定"""
        led_io = self.led_IO['led_IO']
        
        # 檢測是否為已初始化的對象 (有 .buf 和 .n/.Q 屬性)
        if hasattr(led_io, 'buf'):
            self.led = led_io  # 直接使用傳入的對象
            
            # 自動檢測 LED 數量
            if hasattr(led_io, 'n'):
                if self.led_IO['Q'] != led_io.n:
                    print(f"[Warning] Q={self.led_IO['Q']} != led.n={led_io.n}, using led.n")
                    self.led_IO['Q'] = led_io.n
        
        elif self.led_Type == 'RGB':
            # 傳統 neopixel 初始化
            import neopixel
            self.led = neopixel.NeoPixel(
                Pin(led_io, Pin.OUT), 
                self.led_IO['Q'],
                bpp=self.bpp
            )
        
        elif self.led_Type == 'i2c_LED':
            # PCA9685 等 I2C PWM
            self.led = led_io
        
        else:
            raise ValueError(f"Unsupported led_Type: {self.led_Type}")
        
        # 計算幀大小
        self.frame_size = self.led_IO['Q'] * self.bpp
        
        print(f"[LEDcontroller] {self.led_Type} initialized: {self.led_IO['Q']} LEDs, {self.bpp} BPP, {self.frame_size} bytes/frame")
    
    # ========================================
    # 流式傳輸核心方法
    # ========================================
    
    def st_init(self):
        """
        初始化流式傳輸模式
        
        創建流式緩衝區,用於高速數據傳輸
        僅在需要流式傳輸時調用
        """
        try:
            # 創建流式緩衝區 (與硬體緩衝區大小一致)
            if self.led_Type in ('RGB', 'APA102'):
                self.st_buff = bytearray(self.frame_size)
            
            elif self.led_Type == 'i2c_LED':
                # PCA9685: 使用 16-bit 緩衝區
                self.st_buff = array.array('H', [0] * self.led_IO['Q'])
            
            else:
                self.st_buff = bytearray(self.frame_size)
            
            self.streaming_mode = True
            print(f"[LEDcontroller] Streaming mode enabled. Buffer: {len(self.st_buff)} bytes")
        
        except Exception as e:
            print(f"st_init error: {e}")
            self.streaming_mode = False
    
    @micropython.native
    def st_load_from_buffer(self, source_buffer, offset=0):
        """
        流式模式: 從外部緩衝區加載數據
        
        參數:
            source_buffer: 源數據緩衝區 (bytearray 或 memoryview)
            offset: 起始偏移量 (字節)
        
        用於從 LEDStreamer 的大緩衝區讀取一幀
        
        性能: 零拷貝切片操作 (內核級 memmove)
        """
        if not self.streaming_mode or self.st_buff is None:
            return
        
        try:
            # 🚀 Pythonic 高速切片拷貝 (零拷貝技術)
            self.st_buff[:] = source_buffer[offset : offset + self.frame_size]
        
        except Exception as e:
            print(f"st_load_from_buffer error: {e}")
    
    def st_show(self):
        """
        流式模式: 顯示流式緩衝區
        
        將 st_buff 的內容快速拷貝到硬體緩衝區並輸出
        """
        if not self.streaming_mode or self.st_buff is None:
            return
        
        try:
            if self.led_Type in ('RGB', 'APA102'):
                # 🚀 零拷貝: 直接替換硬體緩衝區
                self.led.buf[:] = self.st_buff[:]
                
                # 輸出到硬體
                if hasattr(self.led, 'write'):
                    self.led.write()
                elif hasattr(self.led, 'show'):
                    self.led.show()
            
            elif self.led_Type == 'i2c_LED':
                # PCA9685: 拷貝到控制器緩衝區
                if hasattr(self.led, 'buf'):
                    self.led.buf[:] = self.st_buff[:]
                else:
                    self.led.buffer[:] = self.st_buff[:]
                
                # 同步到硬體
                if hasattr(self.led, 'show'):
                    self.led.show()
                elif hasattr(self.led, 'sync_buffer'):
                    self.led.sync_buffer()
        
        except Exception as e:
            print(f"st_show error: {e}")
    
    def st_close(self):
        """
        關閉流式傳輸模式
        
        釋放流式緩衝區內存
        """
        self.streaming_mode = False
        self.st_buff = None
        gc.collect()
        print("[LEDcontroller] Streaming mode closed")
    
    # ========================================
    # 便捷方法 (用於調試/測試)
    # ========================================
    
    def fill_raw(self, color_tuple):
        """
        直接填充硬體緩衝區 (調試用)
        
        參數:
            color_tuple: (R, G, B) 或 (R, G, B, W)
        """
        if hasattr(self.led, 'fill'):
            self.led.fill(color_tuple)
            if hasattr(self.led, 'write'):
                self.led.write()
            elif hasattr(self.led, 'show'):
                self.led.show()
    
    def clear(self):
        """清空所有 LED"""
        if self.bpp == 4:
            self.fill_raw((0, 0, 0, 0))
        else:
            self.fill_raw((0, 0, 0))


# ==================== LEDStreamer ====================
class LEDStreamer:
    """
    LED 流式傳輸管理器
    
    功能:
    - 管理多個 LEDcontroller
    - 提供統一的大緩衝區
    - 支持順序渲染多個燈帶
    - 零拷貝高速數據傳輸
    
    典型用法:
        # 1. 創建控制器
        led1 = LEDcontroller('RGB', {'led_IO': np1, 'Q': 30, 'order': 'GRB'})
        led2 = LEDcontroller('APA102', {'led_IO': apa, 'Q': 60, 'order': 'RGB'})
        
        # 2. 創建流式管理器
        streamer = LEDStreamer([led1, led2])
        streamer.init()
        
        # 3. 流式播放
        while True:
            # 從文件/網絡/DMA 讀取數據到大緩衝區
            f.readinto(streamer.get_write_view())
            
            # 渲染所有燈帶
            streamer.show_all()
            
            time.sleep_us(interval)
    """
    
    def __init__(self, controllers):
        """
        初始化流式傳輸器
        
        參數:
            controllers: LEDcontroller 列表
        """
        self.controllers = controllers
        self.total_leds = sum(len(c) for c in controllers)
        self.total_bytes = 0
        self.big_buffer = None
        self.offsets = []  # 每個控制器在大緩衝區中的偏移量
        
        print(f"[LEDStreamer] Initialized with {len(controllers)} controllers, {self.total_leds} LEDs")
    
    def init(self):
        """
        初始化流式模式
        
        - 為所有控制器啟用流式模式
        - 創建統一的大緩衝區
        - 計算每個控制器的偏移量
        """
        try:
            # 1. 啟用所有控制器的流式模式
            for ctrl in self.controllers:
                ctrl.st_init()
            
            # 2. 計算總字節數和偏移量
            offset = 0
            for ctrl in self.controllers:
                self.offsets.append(offset)
                frame_size = ctrl.frame_size
                offset += frame_size
                self.total_bytes += frame_size
            
            # 3. 創建大緩衝區
            self.big_buffer = bytearray(self.total_bytes)
            
            print(f"[LEDStreamer] Streaming initialized")
            print(f"  Total buffer: {self.total_bytes} bytes")
            print(f"  Frame offsets: {self.offsets}")
            print(f"  Frame sizes: {[c.frame_size for c in self.controllers]}")
        
        except Exception as e:
            print(f"LEDStreamer init error: {e}")
    
    # ========================================
    # 緩衝區訪問
    # ========================================
    
    def get_read_view(self):
        """
        獲取大緩衝區的只讀視圖 (用於流式讀取)
        
        返回:
            memoryview: 大緩衝區的視圖
        """
        return memoryview(self.big_buffer)
    
    def get_write_view(self):
        """
        獲取大緩衝區的可寫視圖 (用於流式寫入)
        
        返回:
            bytearray: 大緩衝區引用
        
        用法:
            f.readinto(streamer.get_write_view())
        """
        return self.big_buffer
    
    # ========================================
    # 數據加載
    # ========================================
    
    @micropython.native
    def load_buffer(self, source_data, offset=0):
        """
        從外部數據源加載到大緩衝區
        
        參數:
            source_data: 源數據 (bytearray, bytes, memoryview)
            offset: 起始偏移量 (默認0)
        
        用於從文件/網絡/DMA讀取數據
        """
        try:
            copy_size = min(len(source_data) - offset, self.total_bytes)
            self.big_buffer[:copy_size] = source_data[offset : offset + copy_size]
        except Exception as e:
            print(f"load_buffer error: {e}")
    
    # ========================================
    # 渲染控制
    # ========================================
    
    @micropython.native
    def show_all(self):
        """
        順序渲染所有 LEDcontroller
        
        從大緩衝區中提取各自的數據並顯示
        
        性能: 零拷貝切片操作
        """
        try:
            for i, ctrl in enumerate(self.controllers):
                # 從大緩衝區加載數據到控制器的流式緩衝區
                ctrl.st_load_from_buffer(self.big_buffer, self.offsets[i])
                
                # 顯示
                ctrl.st_show()
        except Exception as e:
            print(f"show_all error: {e}")
    
    @micropython.native
    def show_single(self, controller_index):
        """
        僅渲染單個控制器
        
        參數:
            controller_index: 控制器索引
        """
        try:
            if 0 <= controller_index < len(self.controllers):
                ctrl = self.controllers[controller_index]
                ctrl.st_load_from_buffer(self.big_buffer, self.offsets[controller_index])
                ctrl.st_show()
        except Exception as e:
            print(f"show_single error: {e}")
    
    @micropython.native
    def update_and_show(self, controller_index, frame_data):
        """
        更新單個控制器的數據並顯示
        
        參數:
            controller_index: 控制器索引
            frame_data: 幀數據 (bytearray)
        """
        try:
            if 0 <= controller_index < len(self.controllers):
                ctrl = self.controllers[controller_index]
                offset = self.offsets[controller_index]
                frame_size = ctrl.frame_size
                
                # 更新大緩衝區
                self.big_buffer[offset : offset + frame_size] = frame_data[:frame_size]
                
                # 加載並顯示
                ctrl.st_load_from_buffer(self.big_buffer, offset)
                ctrl.st_show()
        except Exception as e:
            print(f"update_and_show error: {e}")
    
    # ========================================
    # 資源管理
    # ========================================
    
    def close(self):
        """
        關閉流式模式
        
        釋放所有緩衝區
        """
        for ctrl in self.controllers:
            ctrl.st_close()
        
        self.big_buffer = None
        self.offsets = []
        gc.collect()
        print("[LEDStreamer] Closed")
    
    # ========================================
    # 便捷方法
    # ========================================
    
    def clear_all(self):
        """清空所有LED"""
        self.big_buffer[:] = b'\x00' * self.total_bytes
        self.show_all()
    
    def get_controller(self, index):
        """獲取指定索引的控制器"""
        if 0 <= index < len(self.controllers):
            return self.controllers[index]
        return None
    
    def get_controller_info(self):
        """獲取所有控制器的詳細信息"""
        info = []
        for i, ctrl in enumerate(self.controllers):
            info.append({
                'index': i,
                'type': ctrl.led_Type,
                'leds': len(ctrl),
                'bpp': ctrl.bpp,
                'order': ctrl.order,
                'frame_size': ctrl.frame_size,
                'offset': self.offsets[i]
            })
        return info


# ==================== 使用範例 ====================
if __name__ == '__main__':
    # ========================================
    # 範例1: 單個 NeoPixel 燈帶
    # ========================================
    """
    import neopixel
    
    # 初始化 NeoPixel
    np = neopixel.NeoPixel(Pin(5), 30, bpp=3)
    
    # 創建控制器
    led = LEDcontroller('RGB', {'led_IO': np, 'Q': 30, 'order': 'GRB'})
    
    # 創建流式管理器
    streamer = LEDStreamer([led])
    streamer.init()
    
    # 創建測試數據 (紅色)
    frame_data = bytearray(30 * 3)  # 30 LEDs × 3 bytes
    for i in range(0, len(frame_data), 3):
        frame_data[i] = 0      # G
        frame_data[i+1] = 255  # R
        frame_data[i+2] = 0    # B
    
    # 加載並顯示
    streamer.load_buffer(frame_data)
    streamer.show_all()
    """
    
    # ========================================
    # 範例2: 多個不同類型的燈帶
    # ========================================
    """
    import neopixel
    from apa102 import APA102
    
    # 初始化燈帶
    np1 = neopixel.NeoPixel(Pin(5), 30, bpp=3)
    np2 = neopixel.NeoPixel(Pin(6), 40, bpp=3)
    apa = APA102(num_leds=50, spi_id=1, sck_pin=8, mosi_pin=7)
    
    # 創建控制器
    led1 = LEDcontroller('RGB', {'led_IO': np1, 'Q': 30, 'order': 'GRB'})
    led2 = LEDcontroller('RGB', {'led_IO': np2, 'Q': 40, 'order': 'GRB'})
    led3 = LEDcontroller('APA102', {'led_IO': apa, 'Q': 50, 'order': 'RGB'})
    
    # 創建流式管理器
    streamer = LEDStreamer([led1, led2, led3])
    streamer.init()
    
    # 查看配置信息
    print(streamer.get_controller_info())
    
    # 創建測試數據
    # total_bytes = 30*3 + 40*3 + 50*3 = 360 bytes
    frame_data = bytearray(360)
    
    # 填充漸變色
    for i in range(0, 360, 3):
        frame_data[i] = (i // 3) % 255      # G
        frame_data[i+1] = 255 - ((i // 3) % 255)  # R
        frame_data[i+2] = ((i // 3) * 2) % 255    # B
    
    # 加載並顯示
    streamer.load_buffer(frame_data)
    streamer.show_all()
    """
    
    # ========================================
    # 範例3: 高速流式播放 (30 FPS)
    # ========================================
    """
    import time
    
    # 假設已初始化 streamer (見範例2)
    
    # 播放參數
    fps = 30
    interval_us = 1_000_000 // fps
    next_tick_us = time.ticks_us()
    
    # 模擬大緩衝區 (例如從SD卡讀取)
    big_data = bytearray(360 * 100)  # 100 幀數據
    
    # 填充測試數據
    for frame_idx in range(100):
        for led_idx in range(120):  # 30+40+50=120 LEDs
            offset = frame_idx * 360 + led_idx * 3
            big_data[offset] = (frame_idx * 2 + led_idx) % 255     # G
            big_data[offset+1] = (255 - frame_idx * 2) % 255       # R
            big_data[offset+2] = led_idx % 255                     # B
    
    # 流式播放循環
    buff_offset = 0
    frame_size = 360
    render_count = 0
    
    while render_count < 100:
        now = time.ticks_us()
        
        if time.ticks_diff(now, next_tick_us) >= 0:
            # 🚀 零拷貝加載一幀
            streamer.load_buffer(big_data, buff_offset)
            
            # 🚀 渲染所有燈帶
            streamer.show_all()
            
            render_count += 1
            buff_offset += frame_size
            next_tick_us += interval_us
            
            # 循環播放
            if buff_offset + frame_size > len(big_data):
                buff_offset = 0
        else:
            time.sleep_us(500)
    
    print(f"Rendered {render_count} frames")
    """
    
    # ========================================
    # 範例4: 從文件流式播放
    # ========================================
    """
    import time
    
    # 假設已初始化 streamer
    
    # 打開動畫文件 (預渲染的 RGB 數據)
    with open('animation.bin', 'rb') as f:
        fps = 30
        interval_us = 1_000_000 // fps
        next_tick_us = time.ticks_us()
        
        # 獲取可寫緩衝區
        write_view = streamer.get_write_view()
        
        while True:
            now = time.ticks_us()
            
            if time.ticks_diff(now, next_tick_us) >= 0:
                # 🚀 直接從文件讀取到緩衝區 (零拷貝)
                bytes_read = f.readinto(write_view)
                
                if bytes_read == 0:
                    # 文件結束,回到開頭
                    f.seek(0)
                    continue
                
                # 🚀 渲染
                streamer.show_all()
                
                next_tick_us += interval_us
            else:
                time.sleep_us(500)
    """
    
    # ========================================
    # 範例5: 單獨控制某個燈帶
    # ========================================
    """
    # 假設已初始化 streamer (有3個燈帶)
    
    # 僅更新第2個燈帶 (索引1)
    led2_data = bytearray(40 * 3)  # 40 LEDs
    for i in range(0, len(led2_data), 3):
        led2_data[i] = 0
        led2_data[i+1] = 0
        led2_data[i+2] = 255  # 藍色
    
    streamer.update_and_show(1, led2_data)
    
    # 或者僅顯示第3個燈帶 (索引2)
    streamer.show_single(2)
    """
    
    pass
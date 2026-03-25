# lvgl_micropython初始化示例（使用官方推薦方式）
import lvgl as lv
import lcd_bus
import machine
from micropython import const
import gc9a01
import time

# --- 硬體配置 ---
_WIDTH = const(240)
_HEIGHT = const(240)
_LCD_FREQ = const(80000000)

# SPI引腳配置
_HOST = const(1)  # SPI主機編號
_MOSI = const(11)
_MISO = const(13)  # 根據您提供的資訊
_SCK = const(10)
_DC = const(8)     # 數據/命令選擇引腳
_LCD_CS = const(9) # 顯示屏片選引腳
_BL_PIN = const(2) # 背光控制引腳

def lvgl_init():
    """使用官方推薦方式初始化LVGL"""
    # 1. 初始化LVGL核心
    lv.init()
    print("LVGL core initialized")
    
    # 2. 初始化SPI總線（官方推薦方式）
    spi_bus = machine.SPI.Bus(
        host=_HOST,
        mosi=_MOSI,
#         miso=_MISO,
        sck=_SCK
    )
    print("SPI Bus initialized")
    
    # 3. 初始化顯示總線
    display_bus = lcd_bus.SPIBus(
        spi_bus=spi_bus,
        freq=_LCD_FREQ,
        dc=_DC,
        cs=_LCD_CS,
    )
    print("Display Bus initialized")
    
    # 4. 創建顯示器驅動實例
    display = gc9a01.GC9A01(
        data_bus=display_bus,
        display_width=_WIDTH,
        display_height=_HEIGHT,
        backlight_pin=_BL_PIN,
        color_space=lv.COLOR_FORMAT.RGB565,
        color_byte_order=gc9a01.BYTE_ORDER_RGB,
        rgb565_byte_swap=True,
    )
    print("Display driver initialized")
    
    # 5. 創建LVGL顯示緩衝
    # 雙緩衝配置（推薦用於動畫）
    buf1 = bytearray(_WIDTH * _HEIGHT * 2)  # RGB565: 2字節/像素
    buf2 = bytearray(_WIDTH * _HEIGHT * 2)
    
    # 6. 創建LVGL顯示驅動
    lv_disp = lv.display_create(_WIDTH, _HEIGHT)
    
    # 7. 設置緩衝區（使用FULL刷新模式）
    lv_disp.set_buffers(
        buf1,
        buf2,
        len(buf1),
        lv.DISPLAY_RENDER_MODE.FULL
    )
    print("Display buffers configured")
    
    # 8. 設置刷新回調
    def flush_cb(disp_drv, area, color_p):
        """顯示刷新回調函數"""
        display.flush_area(
            area.x1, 
            area.y1, 
            area.x2, 
            area.y2, 
            color_p
        )
        lv.disp_flush_ready(disp_drv)
    
    lv_disp.set_flush_cb(flush_cb)
    print("Flush callback set")
    
    # 9. 設置為默認顯示器
    lv.disp_set_default(lv_disp)
    
    # 10. 初始化觸摸（可選，根據實際硬件）
    # touch.init(xp=38, yp=39, xm=40, ym=41, touch_rail=42, touch_sense=43)
    
    return lv_disp, display

def create_hello_world():
    """創建最簡單的Hello World界面"""
    # 獲取當前活動屏幕
    screen = lv.screen_active()
    
    # 創建標籤控件
    label = lv.label(screen)
    
    # 設置文本內容
    label.set_text("Hello LVGL!")
    
    # 居中對齊
    label.center()
    
    # 設置字體樣式
    label.set_style_text_font(lv.font_montserrat_20, 0)
    label.set_style_text_color(lv.palette_main(lv.PALETTE.RED), 0)
    
    return label

def run_main_loop():
    """運行LVGL主循環"""
    try:
        while True:
            # 必須調用此函數來處理LVGL任務
            lv.timer_handler()
            
            # 適當延時以降低CPU使用率
            time.sleep_ms(5)
            
    except KeyboardInterrupt:
        print("\nProgram stopped by user")
    except Exception as e:
        print(f"Error in main loop: {e}")

def main():
    """主程序"""
    print("Starting LVGL Hello World example...")
    
    # 初始化LVGL和硬件
    lv_disp, display = lvgl_init()
    
    # 創建界面
    create_hello_world()
    print("Hello World interface created")
    
    # 運行主循環
    run_main_loop()

# 最簡版本（一行流）
def minimal_example():
    """最簡版本：一行流"""
    # 1. 初始化LVGL
    lv.init()
    
    # 2. 初始化SPI總線（官方方式）
    spi_bus = machine.SPI.Bus(host=1, mosi=11, sck=10)
    
    # 3. 創建顯示總線
    disp_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=80000000, dc=8, cs=9)
    
    # 4. 初始化顯示器
    display = gc9a01.GC9A01(
        disp_bus, 
        display_width=240, 
        display_height=240,
        backlight_pin=2,
        color_space=lv.COLOR_FORMAT.RGB565
    )
    
    display.set_power(True)
    display.init()
    display.set_backlight(100)
    
    scr = lv.screen_active()# Get the currently active screen object
    scr.set_style_bg_color(lv.color_hex(0x000000), 0)# Set the screen background color to black

    slider = lv.slider(scr)# Create a slider
    slider.set_size(100, 25)# Set the slider size to 300 (width) x 50 (height)
    slider.center()# Center the slider

    label = lv.label(scr)# Create a label
    label.set_text('HELLO LVGL_MICROPYTHON!')# Label content
    label.align(lv.ALIGN.CENTER, 0, -50)# Align the label to the center of the screen and offset upward by 50

    # 運行示例
if __name__ == "__main__":
    # 完整版本（推薦）
#     main()
    
    # 或使用最簡版本
    minimal_example()
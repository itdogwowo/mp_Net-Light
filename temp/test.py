# 🚀 高級 LED 系統測試腳本 - 極致性能驗證版
# 目標：驗證多類型混用、色序匹配與流式傳輸效率

import gc
import utime
from machine import Pin, SPI, I2C, SoftI2C
from lib.LEDController import LEDcontroller, LEDStreamer
from lib.pca9685 import PCA9685
from lib.apa102 import APA102
# 假設 LEDcontroller 和 LEDStreamer 已經在命名空間中
# 如果在不同文件，請使用 from your_module import LEDcontroller, LEDStreamer

import math
import utime
import array

GAMMA_TABLE = array.array('H', [
    int(pow(i / 255, 2.8) * 4095) for i in range(256)
])

pca9685 =  {
        'enabled': True,
        'i2c_List':[{
            'i2c_id': 0,
            'scl': 20,
            'sda': 21,
            'address': [0x5B],
            'channels': 16
            }
        ]
    }

apa = APA102(num_leds=10)
led_io = {
            'led_IO': apa,
            'Q': 10,
            'order': 'WBGR'
            }


def init_i2c(led_io):
    i2c_led_list = []
    if led_io['enabled'] :
        for i2cc in led_io['i2c_List']:
            print(i2cc['scl'],i2cc['sda'])
            i2c = I2C(scl=i2cc['scl'], sda=i2cc['sda'])
            #debugPrint(i2c.scan())
            for i in i2c.scan():
                print(hex(i))
            for i in i2cc['address']:
                try:
                    pca = PCA9685(i2c,address=i)
                    pca.freq(1000)
                    # i2c_Object = init_i2c_led(pca)
                    # i2c_led_list.append(i2c_Object)

                    led_IO = {'led_IO':pca,'Q':16}
                    ledPwm = LEDcontroller('i2c_LED',led_IO)
                    i2c_led_list.append(ledPwm)

                except BaseException as e:
                    print(f'missing address : {i}')
                    led_IO = {'led_IO':None,'Q':16}
                    ledPwm = LEDcontroller('i2c_LED',led_IO)
                    i2c_led_list.append(ledPwm)
                    
    return i2c_led_list




controller2 = LEDcontroller('APA102', led_io)
pca = init_i2c(pca9685)
controller = pca[0]

controller.st_init()
controller2.st_init()

buf = controller.st_buff
num_channels = controller.led_IO['Q']

# angle = 0.0
# speed=0.05
# while True:
#     # 2. 計算當前呼吸亮度 (0.0 ~ 1.0)
#     # 使用 sin 函數模擬呼吸起伏
#     brightness_factor = (math.sin(angle) + 1) / 2
#     
#     # 將比例轉換為 0-255，再查 Gamma 表映射到 0-4095 (12-bit PWM)
#     level_8bit = int(brightness_factor * 255)
#     pwm_val = GAMMA_TABLE[level_8bit]
#     
#     # 3. 填充緩衝區
#     # 🚀 這裡我們直接遍歷寫入
#     for i in range(num_channels):
# #         print(pwm_val)
#         buf[i] = pwm_val
#     
#     # 4. 推送到傳輸層並渲染
#     # st_show 會調用 pca.sync_buffer() 或 pca.show()
#     controller.st_show()
#     
#     # 步進角度
#     angle += speed
#     if angle > math.pi * 2:
#         angle = 0
#         
#     # 控制幀率 (約 60 FPS)
#     utime.sleep_ms(16)
    
    
    
controllers = [c for c in [controller,controller2] if c is not None]
streamer = LEDStreamer(controllers)
streamer.init()
    
source_payload = bytearray(streamer.total_leds * 4)
    
print(f"📊 緩衝區分配: {len(source_payload)} Bytes")

angle = 0.0
frames = 200
start_tick = utime.ticks_ms()

try:
    for f in range(frames):
        # 模擬產生 RGBW 數據流
        for i in range(streamer.total_leds):
            idx = i * 4
            # 產生一些色彩變化
            r = int((math.sin(angle + i*0.1) + 1) * 127)
            g = int((math.sin(angle + i*0.1 + 2) + 1) * 127)
            b = int((math.sin(angle + i*0.1 + 4) + 1) * 127)
            # W 通道做亮起落 (專門給 PCA9685 看的)
            w = int((math.cos(angle * 0.5 + i*0.05) + 1) * 127)
            
            source_payload[idx]     = r
            source_payload[idx + 1] = g
            source_payload[idx + 2] = b
            source_payload[idx + 3] = w

        # 🚀 核心測試：加載大緩衝區並顯示
        streamer.load_buffer(source_payload)
        streamer.show_all()

        angle += 0.1
        if f % 50 == 0:
            print(f"  正在播放第 {f} 幀... RAM Free: {gc.mem_free()}")
        
        utime.sleep_ms(10) # 控制在約 60fps

except KeyboardInterrupt:
    print("\n停止測試")

end_tick = utime.ticks_ms()
print("-" * 50)
print(f"🏁 測試完成!")
print(f"平均 FPS: {frames / ((end_tick - start_tick)/1000):.2f}")

streamer.clear_all()
streamer.close()

           




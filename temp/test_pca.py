import machine
import time
import math
from lib.PCA9685 import PCA9685 # 假設你將上面的類存為此檔名

# 1. 硬體初始化 (根據你的實際接線修改 Pin 腳)
# P4 的 I2C 通常建議使用硬體 I2C
i2c = machine.I2C(0, scl=machine.Pin(20), sda=machine.Pin(21), freq=400000)

# 2. 實例化驅動 
# 如果你接的是共陽極 LED (低電平亮)，請設 invert=True
pca = PCA9685(i2c, address=0x5B, n=16, invert=True)

def test_basic_features():
    print("--- 執行基本功能測試 ---")
    
    # 測試單個頻道索引寫入 (你的經典語法)
    print("設置頻道 0 亮度為 2048 (50%)...")
    pca[0][2] = 2048 
    pca.show()
    time.sleep(1)

    # 測試全亮與全滅
    print("全亮...")
    pca.fill(4095)
    pca.show()
    time.sleep(1)
    
    print("全滅...")
    pca.fill(0)
    pca.show()
    time.sleep(1)

def test_batch_update():
    print("--- 執行批量梯度測試 ---")
    # 使用 Python 列表推導式快速更新緩衝區
    pca.buf = [int(i * (4095/15)) for i in range(16)]
    pca.show()
    print("緩衝區當前數值:", list(pca.buf))
    time.sleep(2)

def test_speed_breathing():
    print("--- 執行極速呼吸燈演示 (展示 Viper 效能) ---")
    print("按下 Ctrl+C 結束測試")
    
    count = 0
    try:
        while True:
            # 使用正弦波計算亮度
            # ESP32-P4 運算速度極快，即使在這裡做 math 運算也毫無壓力
            t = time.ticks_ms() / 500.0
            for i in range(16):
                # 每個頻道帶一點相位差，形成流水效果
                brightness = int((math.sin(t + i*0.5) + 1) * 2047.5)
                pca[i][2] = brightness
            
            pca.show()
            
            count += 1
            if count % 100 == 0:
                print(f"目前已刷新 {count} 次...")
                
    except KeyboardInterrupt:
        print("\n測試停止，清空輸出")
        pca.fill(0)
        pca.show()

# ==================== 執行測試 ====================
if __name__ == "__main__":
    try:
        test_basic_features()
        test_batch_update()
        test_speed_breathing()
    except Exception as e:
        print(f"測試過程中出錯: {e}")
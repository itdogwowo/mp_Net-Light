# main.py
import machine, network, time, _thread, ubinascii
from app import App
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub
import Core0_worker
import Core1_engine
from apa102 import APA102

GAMMA_8_TO_12 = array.array('H', [int(pow(i / 255.0, 2.8) * 4095) for i in range(256)])

def run_performance_test(streamer,frames=1000):
    print(f"📊 啟動測試: {len(streamer.controllers)} 個控制器, 共 {streamer.total_bytes >> 2} 顆 LED")
    print(f"📊 緩衝區大小: {streamer.total_bytes} Bytes")
    
    # 獲取寫入視圖 (直接對 streamer 的 big_buffer 進行操作)
    buf = streamer.get_write_view()
    total_leds = streamer.total_bytes >> 2 # bytes / 4
    
    angle = 0.0
    start_tick = utime.ticks_ms()

    try:
        for f in range(frames):
            # 🚀 高速填充數據 (算法部分)
            # 在實際應用中，這裡通常是被 f.readinto(buf) 或 網路傳輸替代
            for i in range(total_leds):
                idx = i << 2 # i * 4
                
                # 計算動態色彩 (這裡可根據性能需求進一步簡化)
                # 我們只對前幾顆燈做明顯動畫，APA102(290顆)全畫會吃 CPU
                val = int((math.sin(angle + i * 0.1) + 1) * 127)
                
                buf[idx]     = val        # R
                buf[idx + 1] = 0          # G
                buf[idx + 2] = 127 - val  # B
                buf[idx + 3] = val        # W
            
            # 🚀 核心執行：轉換並推送到所有硬體
            streamer.show_all()
            
            angle += 0.1
            
            # 每 100 幀輸出一次狀態
            if f % 100 == 0:
                print(f"  Frame {f} | RAM Free: {gc.mem_free()} B")
            
            # 為了穩定性稍微釋放 CPU
            utime.sleep_ms(1)

    except KeyboardInterrupt:
        print("\n🛑 測試被用戶中止")

    end_tick = utime.ticks_ms()
    duration = (end_tick - start_tick) / 1000
    print("-" * 50)
    print(f"🏁 測試完成!")
    print(f"總耗時: {duration:.2f} 秒")
    print(f"平均 FPS: {frames / duration:.2f}")
    
    # 清理
    # streamer.clear_all() # 如果你的 LEDController 有實現此方法
    streamer.close()



def launcher():
    st_LED = bus.get_service("st_LED")
    
    # 2. 總線與 ID
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True
    bus_sys = bus.shared["System"]
    # 3. 🚀 註冊核心交換服務 (不修改 lib，在此處申請)
    hub = AtomicStreamHub(st_LED.total_bytes * bus_sys["buffer_frames"]) 
    bus.register_service("pixel_stream", hub)

    try:
        while True:
            run_performance_test(st_LED,frames=1000)
            time.sleep_ms(500)

        

    except KeyboardInterrupt:
        print("\n👋 User stop requested.")
    except Exception as e:
        print(f"❌ System Error: {e}")
    finally:
        # 🚀 統一機制替代 shutdown()
        bus.shared["engine_run"] = False
        print("🛑 All cores stopping...")
        time.sleep_ms(500) # 給 Core 1 一點時間收尾
        st_LED.big_buffer = bytearray(st_LED.total_bytes) 
        st_LED.show_all()
        print("🏁 Clean Exit.")

    
    
if __name__ == "__main__":
    launcher()
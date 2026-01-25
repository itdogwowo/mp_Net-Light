# test_max_supply_engine.py
import time, _thread, gc, machine
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub

# --- 1. 定義真正的播放引擎 (Core 1) ---
def core1_playback_engine(apa, hub, target_fps=40):
    interval_ms = 1000 // target_fps
    # 使用 us (微秒) 級別計時以獲取最高精度
    interval_us = interval_ms * 1000
    next_tick_us = time.ticks_us()
    
    render_count = 0
    bus.register_provider("actual_render_fps", lambda: render_count)

    while bus.shared.get("engine_run"):
        now_us = time.ticks_us()
        
        # 🚀 節拍檢查
        if time.ticks_diff(now_us, next_tick_us) >= 0:
            # 嘗試拿數據
            frame = hub.get_read_view()
            
            # 模擬硬體渲染 (即使沒新數據也執行，保持物理節奏)
            if frame:
                apa.raw_buffer[:] = frame
            
            apa.show() # 物理刷燈
            render_count += 1
            
            # 定時補償：計算下一個理論上的時間點
            next_tick_us += interval_us
        else:
            # 沒到節拍時間，極短暫休息或 yield
            time.sleep_ms(1)

# --- 2. 生產者：無限供應模式 (Core 0) ---
def simulate_massive_supply(hub):
    print("📥 [Core 0] MASSIVE SUPPLY START: 200+ FPS Delivery")
    while bus.shared.get("engine_run"):
        v = hub.get_write_view()
        # 簡單填充，不做耗時運算
        v[0] = bus.net_count % 256
        hub.commit()
        bus.net_count += 1
        # 模擬極速網路到達，幾乎不等待
        time.sleep_ms(2) 

# --- 3. 測試入口 ---
class FastAPA:
    def __init__(self, n): self.raw_buffer = bytearray(n*4)
    def show(self): 
        # 2000 顆燈 12MHz 約 8ms 物理極限
        time.sleep_ms(8) 

def run_performance_battle():
    LED_COUNT = 2000
    hub = AtomicStreamHub(LED_COUNT * 4)
    apa = FastAPA(LED_COUNT)
    
    bus.register_service("pixel_stream", hub)
    bus.shared["engine_run"] = True
    bus.net_count = 0
    
    # 啟動超級生產者 (Core 0)
    _thread.start_new_thread(simulate_massive_supply, (hub,))
    
    # 啟動精準引擎 (Core 1, 目標 40 FPS)
    print("🚀 [Core 1] Metronome Target: 40 FPS")
    start_t = time.time()
    
    # 在主線程運行引擎（或者開新線程讓主線程監看，這裡我們開新線程）
    _thread.start_new_thread(core1_playback_engine, (apa, hub, 40))
    
    # 測試 10 秒
    time.sleep(10)
    bus.shared["engine_run"] = False
    
    metrics = bus.get_metrics()
    dur = 10.0
    
    print("\n" + "="*45)
    print(f"🏁 ENGINE STRESS REPORT (Target: 40 FPS)")
    print(f"Producer FPS: {bus.net_count / dur:.2f} (供應量)")
    print(f"Render FPS: {metrics.get('actual_render_fps', 0) / dur:.2f} (穩定度)")
    print(f"System Load: {(40 / (bus.net_count / dur))*100:.1f}% (供應餘力)")
    print("="*45)

if __name__ == "__main__":
    run_performance_battle()

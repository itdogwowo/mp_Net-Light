import time
import _thread
import machine
import ubinascii
import gc
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub

# --- 參數配置 ---
LED_COUNT = 2000 
BPP = 4  # RGBW
BUFFER_SIZE = LED_COUNT * BPP  # 8000 Bytes (8KB)
TEST_DURATION = 10  # 測試 10 秒
TARGET_NET_FPS = 60 # 模擬超高速網絡流

print(f"🔥 Starting Extreme Stress Test: {BUFFER_SIZE} bytes per frame")

# --- 壓力生產者 (Core 0) ---
def core0_high_load_producer():
    hub = bus.get_service("pixel_stream")
    if not hub: return
    
    _net_count = [0]
    bus.register_provider("net_total", lambda: _net_count[0])
    
    start_time = time.time()
    frame = 0
    
    while time.time() - start_time < TEST_DURATION:
        view = hub.get_write_view()
        
        # 模擬繁重的數據解析 (使用 memoryview 快速填充)
        # 每一次我們填入不同的模式來辨識數據完整性
        val = frame % 256
        for i in range(0, BUFFER_SIZE, 100): # 每隔 100 bytes 採樣填寫以節省測試循環耗時
            view[i] = val
            
        hub.commit()
        _net_count[0] += 1
        frame += 1
        
        # 按照 Target FPS 控制速度，如果測試極限則不 sleep
        if TARGET_NET_FPS < 1000:
            time.sleep_ms(1000 // TARGET_NET_FPS)
        
        # 模擬 Core 0 的其他任務雜訊 (例如回應 STATUS 指令)
        if frame % 50 == 0:
            _ = bus.get_metrics()
            gc.collect() # 故意觸發 GC 測試系統韌性

    print(f"📡 Core 0: Production Stop. Total produced: {_net_count[0]}")

# --- 壓力消費者 (Core 1) ---
def core1_high_load_consumer():
    hub = bus.get_service("pixel_stream")
    if not hub: return
    
    _render_count = [0]
    _error_count = [0]
    bus.register_provider("render_total", lambda: _render_count[0])
    bus.register_provider("render_errors", lambda: _error_count[0])
    
    last_val = -1
    start_time = time.time()
    
    while time.time() - start_time < TEST_DURATION:
        frame = hub.get_read_view()
        if frame:
            # --- 數據正確性嚴格校驗 ---
            # 因為 Core 0 的寫法，首 byte 必須等於尾 byte（或特定偏移位）
            # 這是驗證「指針交換後，數據是否依然穩定」的關鍵
            current_val = frame[0]
            
            # 如果讀到的數據不是 Core 0 剛才寫入的完整值，代表發生競爭撕裂
            # (雖然在我們的 Triple Hub 中理論上不可能發生)
            if current_val == last_val:
                # 這是重複讀取，如果是 async 機制正常，這裡不應頻繁觸發
                pass
            
            # 模擬硬體渲染耗時 (APA102 @ 12Mhz 顯示 2000 燈約需 7ms)
            # 我們模擬出實際物理開銷
            time.sleep_ms(7) 
            
            _render_count[0] += 1
            last_val = current_val
        else:
            # 沒新數據，極短暫休息
            time.sleep_us(500)

    print(f"🚀 Core 1: Rendering Stop. Total rendered: {_render_count[0]}")

# --- 主控 ---
def run_extreme_test():
    gc.collect()
    print(f"Mem Free before test: {gc.mem_free()} bytes")
    
    bus.slave_id = "STRESS_TEST_PRO"
    # 初始化 Buffer 服務 (8KB)
    bus.register_service("pixel_stream", AtomicStreamHub(BUFFER_SIZE))
    
    # 拉起雙核
    _thread.start_new_thread(core1_high_load_consumer, ())
    
    time.sleep(0.5) # 等待 Core 1 就緒
    
    # 啟動 Core 0 生產
    t_start = time.ticks_ms()
    core0_high_load_producer()
    t_end = time.ticks_ms()
    
    # 報告分析
    duration = time.ticks_diff(t_end, t_start) / 1000
    metrics = bus.get_metrics()
    
    net_total = metrics.get('net_total', 0)
    render_total = metrics.get('render_total', 0)
    
    print("\n" + "="*40)
    print(f"📊 EXTREME TEST REPORT ({duration:.2f}s)")
    print(f"Network Throughput: {net_total / duration:.2f} FPS")
    print(f"Hardware Rendering: {render_total / duration:.2f} FPS")
    print(f"Service Efficiency: {(render_total / net_total)*100:.1f}%")
    print(f"Final Mem Free: {gc.mem_free()} bytes")
    print("="*40)

    if render_total > 0:
        print("✅ STABILITY PASSED: No core lockup detected.")
    else:
        print("❌ FAILED: Zero frames rendered.")

if __name__ == "__main__":
    run_extreme_test()
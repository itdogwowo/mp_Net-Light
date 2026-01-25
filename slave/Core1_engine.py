# Core1_engine.py
import time
from lib.sys_bus import bus

def task_loop(apa, fps=40):
    hub = None
    while hub is None:
        hub = bus.get_service("pixel_stream")
        time.sleep_ms(100)

    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()
    render_count = 0
    bus.register_provider("actual_fps", lambda: render_count)

    print(f"🔥 [Core 1] Render Engine Online | {fps} FPS")
    try:
        while bus.shared.get("engine_run", True):
            now_us = time.ticks_us()
            
            if time.ticks_diff(now_us, next_tick_us) >= 0:
                # 獲取 Core 0 準備好的資料
                frame = hub.get_read_view()
                if frame:
                    apa.raw_buffer[:] = frame
                    render_count += 1
                
                # 無論是否新數據，時間到了就 show (如果是 local 播完暫停，這裡可以加判斷)
                apa.show()
                next_tick_us += interval_us
            else:
                time.sleep_ms(1)
            
    finally:
        # 🚀 退出時關閉燈光，這對硬體保護很重要
        apa.clear()
        apa.show()
        print("⏹️ [Core 1] Render task terminated.")
# Core1_engine.py
import time
from lib.sys_bus import bus

def task_loop(apa, fps=40):
    hub = None
    while hub is None:
        hub = bus.get_service("pixel_stream")
        time.sleep_ms(100)
        
    # 🚀 關鍵：建立 Core 1 專用計數器
    _state = {"render_count": 0}
    # 將計數器註冊到總線，命名為 render_fps
    bus.register_provider("render_fps", lambda: _state["render_count"])
    
    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()
    
    print(f"🔥 [Core 1] Render Engine Online | {fps} FPS")

    while bus.shared.get("engine_run", True):
        # 🚀 停止模式：關燈
        if not bus.shared.get("is_streaming"):
            if bus.shared.get("is_ready") == False:
                apa.raw_buffer[:] = bytearray(len(apa.raw_buffer)) # 清空
                apa.show()
            time.sleep_ms(100)
            next_tick_us = time.ticks_us() # 重置防止緩衝區爆發
            _state["render_count"] = 0 # 停止時清零
            continue

        # 🚀 暫停模式：定格
        if bus.shared.get("is_paused"):
            time.sleep_ms(50)
            next_tick_us = time.ticks_us()
            _state["render_count"] = 0
            continue

        # 🚀 播放模式：死守時鐘
        now = time.ticks_us()
        if time.ticks_diff(now, next_tick_us) >= 0:
            frame = hub.get_read_view()
            if frame:
                apa.raw_buffer[:] = frame # 同步緩衝
                _state["render_count"] += 1
            apa.show()
            next_tick_us += interval_us
        else:
            time.sleep_ms(1)
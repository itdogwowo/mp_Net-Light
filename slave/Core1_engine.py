# Core1_engine.py
import time
from lib.sys_bus import bus
from lib.fs_manager import fs

def task_loop(st_LED, fps=40):
    hub = None
    while hub is None:
        hub = bus.get_service("pixel_stream")
        time.sleep_ms(100)
        
    # 🚀 關鍵：建立 Core 1 專用計數器
    _state = {"render_count": 0}
    # 將計數器註冊到總線，命名為 render_fps
    bus.register_provider("render_fps", lambda: _state["render_count"])
    bus.shared["core1_ready"] = True
    
    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()

    # --- 💎 性能優化：預先緩存常量與局部變量 💎 ---
    frame_size = len(st_LED.big_buffer) # 單幀所需的字節數
    current_big_buffer = None        # 當前從 Hub 拿到的超大原始 Buff
    buff_offset = 0                  # 當前讀取偏移量


    raw_view = st_LED.big_buffer
    
    print(f"🔥 [Core 1] Render Engine Online | {fps} FPS")

    while bus.shared.get("engine_run", True):
        # 🚀 0. 系統任務檢查 (優先級最高，會阻塞渲染)
        if bus.shared.get("fs_scan_requested"):
            fs.perform_scan()
            bus.shared["fs_scan_requested"] = False
            next_tick_us = time.ticks_us() # 掃描完後重置時間基準
            
        # 🚀 停止模式：關燈
        if not bus.shared.get("is_streaming"):
            if bus.shared.get("is_ready") == False:
                st_LED.big_buffer[:] = bytearray(frame_size) # 清空
                st_LED.show_all()
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
            # 🚀 流式讀取邏輯：如果當前大 Buffer 用完了或還沒有，去 Hub 拿新的
            if current_big_buffer is None or buff_offset + frame_size > len(current_big_buffer):
                current_big_buffer = hub.get_read_view() # 這是核心同步點
                buff_offset = 0 # 重置偏移量
                
            if current_big_buffer:
                # 🐍 Pythonic 高速切片拷貝 (內核級別 memmove)
                # 從大緩存中提取一幀到 apa 的顯存中
                raw_view[:] = current_big_buffer[buff_offset : buff_offset + frame_size]
                st_LED.show_all()
                _state["render_count"] += 1
                buff_offset += frame_size
            next_tick_us += interval_us
        else:
            time.sleep_us(500) 

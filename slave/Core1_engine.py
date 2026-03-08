# Core1_engine.py
import time
from lib.sys_bus import bus

def task_loop(st_LED, fps=40):
    # 預設 Hub 名稱
    current_hub_name = "pixel_stream"
    hub = None
    
    # 初始等待 (但不要死循環，允許後續動態綁定)
    print("⏳ [Core 1] Waiting for pixel_stream service...")
    retry = 0
    while hub is None and retry < 20:
        hub = bus.get_service(current_hub_name)
        if hub: break
        time.sleep_ms(100)
        retry += 1
        
    # 🚀 關鍵：建立 Core 1 專用計數器
    _state = {"render_count": 0}
    # 將計數器註冊到總線，命名為 render_fps
    bus.register_provider("render_fps", lambda: _state["render_count"])
    
    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()

    # --- 💎 性能優化：預先緩存常量與局部變量 💎 ---
    frame_size = len(st_LED.big_buffer) # 單幀所需的字節數
    current_big_buffer = None        # 當前從 Hub 拿到的超大原始 Buff
    buff_offset = 0                  # 當前讀取偏移量


    raw_view = st_LED.big_buffer
    
    print(f"🔥 [Core 1] Render Engine Online | {fps} FPS")

    # 預先緩存 bus.shared 以減少查找
    shared_bus = bus.shared
    ctrl_bus = None

    while shared_bus.get("engine_run", True):
        # 0. 🚀 [Core 1] 數據解碼任務 (如果啟用)
        # 檢查是否啟用 Core 1 解碼
        if shared_bus.get("decode_core", 0) == 1:
            if ctrl_bus is None:
                ctrl_bus = bus.get_service("ctrl_bus")
            
            if ctrl_bus:
        # 主動調用 NetBus 進行數據解析 (Hub -> App)
        # 這會分擔 Core 0 的 CPU 壓力，讓其專注於 socket.readinto
        ctrl_bus.process_ingress()

    # 1. 🚀 [Core 1] 文件後台寫入任務
    # 這允許 Core 0 快速將文件數據寫入 Hub 並返回 ACK，而 Core 1 慢慢寫 Flash
    if app and hasattr(app, 'file_rx'):
        app.file_rx.process_hub_data()

    # 2. 🔄 動態切換 Service (支援 Benchmark 或多路流)
    target_name = shared_bus.get("stream_service", "pixel_stream")
        if target_name != current_hub_name:
            new_hub = bus.get_service(target_name)
            if new_hub:
                print(f"🔄 [Core 1] Switching to Hub: {target_name}")
                hub = new_hub
                current_hub_name = target_name
                # 重置緩衝狀態，避免舊數據干擾
                current_big_buffer = None
                buff_offset = 0

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

        # 🚀 播放模式：死守時鐘 (除非是 Turbo 模式)
        now = time.ticks_us()
        is_turbo = bus.shared.get("turbo_mode", False)
        
        if is_turbo or time.ticks_diff(now, next_tick_us) >= 0:
            # 🚀 流式讀取邏輯：如果當前大 Buffer 用完了或還沒有，去 Hub 拿新的
            if current_big_buffer is None or buff_offset + frame_size > len(current_big_buffer):
                # 嘗試釋放舊 buffer (如果還沒釋放)
                current_big_buffer = None 
                
                current_big_buffer = hub.get_read_view() # 這是核心同步點
                buff_offset = 0 # 重置偏移量
                
                # Debug: 打印成功獲取 buffer
                if current_big_buffer and is_turbo:
                    # print(f"🚀 [Core1] Got Buffer: {len(current_big_buffer)}")
                    pass
                
            if current_big_buffer:
                # 🐍 Pythonic 高速切片拷貝 (內核級別 memmove)
                # 從大緩存中提取一幀到 apa 的顯存中
                raw_view[:] = current_big_buffer[buff_offset : buff_offset + frame_size]
                
                # 🚀 Turbo 模式下跳過物理 LED 輸出，以測試最大傳輸吞吐量
                if not is_turbo:
                    st_LED.show_all()
                    
                _state["render_count"] += 1
                buff_offset += frame_size
            else:
                # 🛡️ Turbo Mode Protection: 
                # 如果緩衝區為空 (Writer 還沒來得及寫)，必須短暫 sleep 釋放 CPU/GIL
                # 否則會導致 Core0 (Network) 被餓死，無法接收數據
                if is_turbo:
                    time.sleep_ms(1)
            
            if not is_turbo:
                next_tick_us += interval_us
        else:
            time.sleep_us(500) 
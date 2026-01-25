# Core1_engine.py
import time
from lib.sys_bus import bus

def task_loop(apa, fps=40):
    """
    Core 1 執行主循環
    :param apa: 硬件驅動實例 (需具備 raw_buffer 屬性與 show() 方法)
    :param fps: 強制鎖定的播放幀率
    """
    # 🚀 [規範] 從總線獲取服務，若 App 還沒註冊 stream，則持續等待
    # 這體現了「服務發現」機制，不需要強耦合特定模組
    hub = None
    while hub is None:
        hub = bus.get_service("pixel_stream")
        if hub is None:
            time.sleep_ms(100) # 服務尚未就緒，低功耗等待

    # 🚀 [規範] 建立本地計數器，並註冊到總線提供者
    # 消費者獨立記賬，Core 0 或 PC 隨時可以查詢
    render_count = 0
    bus.register_provider("render_fps", lambda: render_count)

    # 🚀 [算法] 絕對物理時鐘精準補償
    # 使用 interval_us (微秒) 避開 Python 浮點數誤差
    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()

    print(f"🔥 [Core 1] Render Engine Online | Target: {fps} FPS")

    while bus.shared.get("engine_run", True):
        now_us = time.ticks_us()
        
        # 🚀 [核心邏輯] 檢查節拍器是否到達
        if time.ticks_diff(now_us, next_tick_us) >= 0:
            
            # --- 獲取數據區 ---
            # 從物流中心 (Hub) 提取 Core 0 提交的最新視圖
            # 若無新數據 (dirty=False)，get_read_view 會返回 None
            frame = hub.get_read_view()
            
            if frame:
                # 若有新數據，將 Hub 緩衝區同步到硬件緩衝區
                # 這裡的賦值在內存層級是高效的內存搬運
                apa.raw_buffer[:] = frame
                render_count += 1 # 僅在有新幀時增加計數 (代表有效渲染)
            
            # --- 硬件輸出區 ---
            # 不論數據是否有更新，物理時鐘到了就執行刷燈
            # 這樣可以保持燈珠的高頻閃動一致性
            apa.show()
            
            # 🚀 [補償] 更新下一個理論節拍時間點
            # 注意：不是 now_us + interval，而是基於上一個節拍
            # 這保證了即便某次 show() 慢了，下一次也會自動追趕回來
            next_tick_us += interval_us
            
        else:
            # 🚀 [性能] 沒到時間，主動釋放 CPU
            # 讓 MicroPython 的排程器能處理核心 0 或線程切換
            time.sleep_ms(1)
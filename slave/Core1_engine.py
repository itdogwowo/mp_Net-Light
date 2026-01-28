# Core1_engine.py
"""
Core 1 渲染引擎
═══════════════════════════════════════════════════════
職責:
- 從 Hub 讀取幀數據
- 驅動 APA102/WS2812
- 維護本地幀計數器
- 死守目標 FPS
"""
import time
from lib.sys_bus import bus

def task_loop(apa, fps=40):
    """
    Core 1 主循環
    ───────────────────────────────────────────────────
    """
    # 等待 Hub 初始化
    hub = None
    while hub is None:
        hub = bus.get_service("pixel_stream")
        time.sleep_ms(100)
    
    # 獲取共享狀態
    stream_state = bus.shared.get("stream_state", {})
    playback = bus.shared.get("playback", {})
    slot_meta = bus.shared.get("slot_meta", {})
    
    # 註冊 Provider
    render_state = {"count": 0}
    bus.register_provider("render_fps", lambda: render_state["count"])
    
    # 計算幀間隔
    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()
    
    # 幀配置
    num_leds = bus.shared.get("num_leds", 2000)
    bytes_per_frame = num_leds * 4
    f_per_block = stream_state.get("f_per_block", 500)
    
    print(f"🔥 [Core 1] Render Engine @ {fps} FPS")
    
    while bus.shared.get("engine_run", True):
        
        # ══════════════════════════════════════════════
        # [停止模式] 黑屏
        # ══════════════════════════════════════════════
        if not stream_state.get("is_streaming"):
            apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
            apa.show()
            time.sleep_ms(100)
            next_tick_us = time.ticks_us()
            render_state["count"] = 0
            continue
        
        # ══════════════════════════════════════════════
        # [暫停模式] 定格
        # ══════════════════════════════════════════════
        if stream_state.get("is_paused"):
            time.sleep_ms(50)
            next_tick_us = time.ticks_us()
            continue
        
        # ══════════════════════════════════════════════
        # [播放模式] 死守時鐘
        # ══════════════════════════════════════════════
        now = time.ticks_us()
        
        if time.ticks_diff(now, next_tick_us) >= 0:
            # 獲取當前槽位
            slot_idx, view = hub.get_read_view()
            
            if slot_idx is not None and view:
                # 獲取槽位的業務數據
                meta = slot_meta.get(slot_idx, {})
                local_frame = playback.get("local_frame", 0)
                
                # 🚀 檢查是否切換了槽位
                if playback.get("active_slot") != slot_idx:
                    # 新槽位開始
                    playback["active_slot"] = slot_idx
                    playback["active_block"] = meta.get("block_id", -1)
                    playback["start_frame"] = meta.get("frame_offset", 0)
                    playback["local_frame"] = meta.get("frame_offset", 0)
                    playback["block_start_time"] = time.ticks_ms()
                    playback["render_count"] = 0
                    
                    local_frame = playback["local_frame"]
                    
                    print(f"🔄 [Core 1] Playing Slot {slot_idx} (Block {meta.get('block_id')}, Frame {meta.get('frame_offset')})")
                
                # 計算幀偏移
                offset = local_frame * bytes_per_frame
                
                # 邊界檢查
                if offset + bytes_per_frame <= len(view):
                    # 讀取幀數據
                    frame_view = view[offset : offset + bytes_per_frame]
                    apa.raw_buffer[:] = frame_view
                    
                    # 更新計數器
                    render_state["count"] += 1
                    playback["local_frame"] += 1
                    playback["global_frame"] += 1
                    playback["render_count"] += 1
                else:
                    # 超出邊界,顯示黑屏
                    apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
            else:
                # 無數據,黑屏
                apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
            
            # 輸出到 LED
            apa.show()
            
            # 更新時間戳
            next_tick_us += interval_us
            
            # ══════════════════════════════════════════
            # [檢查 Block 完成]
            # ══════════════════════════════════════════
            if playback.get("local_frame", 0) >= f_per_block:
                # 播完一個 Block
                current_slot = playback.get("active_slot")
                
                if current_slot is not None:
                    # 回調 stream_actions
                    from action.stream_actions import on_block_complete
                    on_block_complete(current_slot)
                    
                    # 釋放槽位
                    hub.release()
                
                # 重置計數器
                playback["local_frame"] = 0
                playback["start_frame"] = 0
                playback["render_count"] = 0
                playback["block_start_time"] = time.ticks_ms()
        else:
            # 還沒到時間
            time.sleep_ms(1)
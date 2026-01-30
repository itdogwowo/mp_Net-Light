"""
Core 1 渲染引擎
═══════════════════════════════════════════════════════
職責:
- 從 Flash/RAM 讀取幀數據
- 驅動 LED
- 死守 FPS
"""
import time
from lib.sys_bus import bus

def _read_frame_from_flash(fd, frame_idx, num_leds):
    """從 Flash 讀取幀"""
    frame_size = num_leds * 4
    offset = frame_idx * frame_size
    
    try:
        fd.seek(offset)
        data = fd.read(frame_size)
        
        if len(data) != frame_size:
            return None
        
        return data
    except Exception as e:
        print(f"❌ [Core 1] Read Failed: {e}")
        return None

def task_loop(apa, fps=40):
    """Core 1 主循環"""
    print("🎨 [Core 1] Waiting for Hub...")
    
    hub = None
    while hub is None:
        hub = bus.get_service("pixel_stream")
        time.sleep_ms(100)
    
    while not bus.shared.get("stream_config", {}).get("initialized"):
        time.sleep_ms(100)
    
    config = bus.shared["stream_config"]
    playback = bus.shared["playback"]
    slot_meta = bus.shared["slot_meta"]
    control = bus.shared["stream_control"]
    
    render_state = {"count": 0}
    bus.register_provider("render_total_count", lambda: render_state["count"])
    
    interval_us = (1000 // config["fps"]) * 1000
    next_tick_us = time.ticks_us()
    
    num_leds = config["num_leds"]
    bytes_per_frame = num_leds * 4
    f_per_block = config["f_per_block"]
    
    current_slot = -1
    current_fd = None
    
    print(f"🔥 [Core 1] Render Engine @ {config['fps']} FPS")
    
    while bus.shared.get("engine_run", True):
        # 中斷處理
        if control.get("abort_now"):
            if current_fd:
                current_fd.close()
                current_fd = None
            
            apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
            apa.show()
            
            if current_slot >= 0:
                from action.stream_actions import on_block_complete
                on_block_complete(current_slot, interrupted=True)
                hub.release()
            
            current_slot = -1
            playback["local_frame"] = 0
            control["abort_now"] = False
            next_tick_us = time.ticks_us()
            continue
        
        # 停止模式
        if not playback.get("is_streaming"):
            apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
            apa.show()
            time.sleep_ms(100)
            next_tick_us = time.ticks_us()
            render_state["count"] = 0
            continue
        
        # 暫停模式
        if playback.get("is_paused"):
            time.sleep_ms(50)
            next_tick_us = time.ticks_us()
            continue
        
        # 播放模式
        now = time.ticks_us()
        
        if time.ticks_diff(now, next_tick_us) >= 0:
            slot_idx, view = hub.get_read_view()
            
            if slot_idx is not None:
                meta = slot_meta.get(slot_idx, {})
                
                # 切換槽位
                if current_slot != slot_idx:
                    if current_fd:
                        current_fd.close()
                        current_fd = None
                    
                    if meta.get("type") == "flash":
                        file_path = meta.get("file_path")
                        try:
                            current_fd = open(file_path, "rb")
                            print(f"📂 [Core 1] Opened: {file_path}")
                        except Exception as e:
                            print(f"❌ [Core 1] Open Failed: {e}")
                            from action.stream_actions import send_error, ERROR_FILE_NOT_FOUND
                            send_error(ERROR_FILE_NOT_FOUND, meta.get("block_id", -1), slot_idx, str(e))
                            hub.release()
                            current_slot = -1
                            continue
                    
                    current_slot = slot_idx
                    playback["active_slot"] = slot_idx
                    playback["active_block"] = meta.get("block_id", -1)
                    playback["local_frame"] = meta.get("frame_offset", 0)
                    playback["start_frame"] = playback["local_frame"]
                    playback["block_start_time"] = time.ticks_ms()
                    playback["render_count"] = 0
                    
                    print(f"🔄 [Core 1] Playing Slot {slot_idx} (Block {meta.get('block_id')})")
                
                # 讀取幀數據
                if meta["type"] == "flash":
                    if not current_fd:
                        continue
                    
                    data = _read_frame_from_flash(
                        current_fd,
                        playback["local_frame"],
                        num_leds
                    )
                else:  # RAM
                    offset = playback["local_frame"] * bytes_per_frame
                    if offset + bytes_per_frame <= len(view):
                        data = view[offset : offset + bytes_per_frame]
                    else:
                        data = None
                
                if data:
                    apa.raw_buffer[:] = data
                else:
                    apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
                
                apa.show()
                
                render_state["count"] += 1
                playback["local_frame"] += 1
                playback["global_frame"] += 1
                playback["render_count"] += 1
                
                # Block 完成
                if playback["local_frame"] >= f_per_block:
                    if current_fd:
                        current_fd.close()
                        current_fd = None
                    
                    from action.stream_actions import on_block_complete
                    on_block_complete(current_slot, interrupted=False)
                    
                    hub.release()
                    current_slot = -1
                    playback["local_frame"] = 0
            else:
                apa.raw_buffer[:] = bytearray(len(apa.raw_buffer))
                apa.show()
            
            next_tick_us += interval_us
            
            from action.stream_actions import check_auto_report
            check_auto_report()
        else:
            time.sleep_ms(1)
    
    print("🛑 [Core 1] Stopped")
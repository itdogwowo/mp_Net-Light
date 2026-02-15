# Core1_engine.py
import time
import hashlib
import ubinascii
from lib.sys_bus import bus
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

def task_loop(st_LED, fps=40):
    """CPU 1 主循環 - 渲染 + 文件寫入"""
    
    # 等待 Hub 初始化
    render_hub = None
    while render_hub is None:
        render_hub = bus.get_service("pixel_stream")
        time.sleep_ms(100)
    
    # 渲染狀態
    render_state = {
        "render_count": 0,
        "current_big_buffer": None,
        "buff_offset": 0
    }
    bus.register_provider("render_fps", lambda: render_state["render_count"])
    
    interval_us = (1000 // fps) * 1000
    next_tick_us = time.ticks_us()
    frame_size = len(st_LED.big_buffer)
    raw_view = st_LED.big_buffer
    
    # 文件寫入狀態
    file_state = {
        "last_check": time.ticks_ms(),
        "is_writing": False
    }
    
    print(f"🔥 [Core 1] Engine Online | Render: {fps} FPS")
    
    while bus.shared.get("engine_run", True):
        # ══════════════════════════════════════════
        #  Task 1: 文件寫入 (異步獨立)
        # ══════════════════════════════════════════
        now_ms = time.ticks_ms()
        
        if time.ticks_diff(now_ms, file_state["last_check"]) > 50:
            rx_state = bus.shared.get("file_rx_state")
            
            if (rx_state and 
                rx_state.get("start_write") and 
                not rx_state.get("write_done") and
                not file_state["is_writing"]):
                
                mode = rx_state.get("mode")
                
                # ========== BIG BUFFER 寫入 ==========
                if mode == "BIG_BUFFER":
                    file_state["is_writing"] = True
                    
                    big_buffer_view = bus.get_service("file_big_buffer")
                    
                    if big_buffer_view:
                        try:
                            import hashlib
                            import ubinascii
                            
                            total_size = rx_state["total_size"]
                            path = rx_state["path"]
                            
                            print(f"📝 [CPU1] Writing {total_size // 1024} KB...")
                            
                            # 🔥 分塊寫入並報告進度
                            start = time.ticks_ms()
                            last_report = start
                            written = 0
                            
                            WRITE_CHUNK = 32 * 1024  # 每次寫 32KB
                            
                            with open(path, "wb") as fp:
                                while written < total_size:
                                    chunk_size = min(WRITE_CHUNK, total_size - written)
                                    
                                    # 寫入分塊
                                    fp.write(big_buffer_view[written : written + chunk_size])
                                    written += chunk_size
                                    
                                    # 🔥 每 256KB 報告一次進度
                                    now = time.ticks_ms()
                                    if time.ticks_diff(now, last_report) > 500 or written >= total_size:
                                        elapsed = time.ticks_diff(now, start) / 1000
                                        speed = (written / 1024) / elapsed if elapsed > 0 else 0
                                        progress = (written / total_size) * 100
                                        
                                        print(f"💾 [CPU1] {progress:5.1f}% | {speed:6.1f} KB/s")
                                        last_report = now
                                
                                fp.flush()
                            
                            elapsed_total = time.ticks_diff(time.ticks_ms(), start)
                            avg_speed = (total_size / 1024) / (elapsed_total / 1000)
                            
                            print(f"⚡ [CPU1] Done: {avg_speed:.1f} KB/s ({elapsed_total} ms)")
                            
                            # 🔥 校驗
                            final_sha = hashlib.sha256(big_buffer_view).digest()
                            rx_state["final_sha"] = ubinascii.hexlify(final_sha).decode()
                            rx_state["verify_ok"] = (final_sha == rx_state["sha256"])
                            
                            print(f"🔒 [CPU1] SHA: {rx_state['final_sha'][:16]}...")
                            
                            # 🔥 發送通知
                            ctrl_bus = bus.shared.get("ctrl_bus_ref")
                            store = bus.get_service("schema_store")
                            
                            if ctrl_bus and ctrl_bus.connected and store:
                                from lib.schema_codec import SchemaCodec
                                from lib.proto import Proto
                                
                                written_def = store.get(0x2008)
                                written_data = SchemaCodec.encode(written_def, {
                                    "file_id": rx_state.get("file_id", 1),
                                    "success": 1 if rx_state["verify_ok"] else 0,
                                    "sha256": final_sha,
                                    "error_msg": ""
                                })
                                ctrl_bus.write(Proto.pack(0x2008, written_data))
                                print(f"📡 [CPU1] WRITTEN sent")
                            
                            rx_state["write_done"] = True
                        
                        except Exception as e:
                            print(f"❌ [CPU1] {e}")
                            import sys
                            sys.print_exception(e)
                            rx_state["error"] = str(e)
                            rx_state["verify_ok"] = False
                            rx_state["write_done"] = True
                        
                        finally:
                            file_state["is_writing"] = False
            
            file_state["last_check"] = now_ms
        
        # ══════════════════════════════════════════
        #  Task 2: LED 渲染引擎
        # ══════════════════════════════════════════
        if not bus.shared.get("is_streaming"):
            if bus.shared.get("is_ready") == False:
                st_LED.big_buffer[:] = bytearray(frame_size)
                st_LED.show_all()
            time.sleep_ms(50)
            next_tick_us = time.ticks_us()
            render_state["render_count"] = 0
            continue
        
        if bus.shared.get("is_paused"):
            time.sleep_ms(50)
            next_tick_us = time.ticks_us()
            render_state["render_count"] = 0
            continue
        
        # 時鐘控制
        now_us = time.ticks_us()
        if time.ticks_diff(now_us, next_tick_us) >= 0:
            if (render_state["current_big_buffer"] is None or 
                render_state["buff_offset"] + frame_size > len(render_state["current_big_buffer"])):
                
                render_state["current_big_buffer"] = render_hub.get_read_view()
                render_state["buff_offset"] = 0
            
            if render_state["current_big_buffer"]:
                raw_view[:] = render_state["current_big_buffer"][
                    render_state["buff_offset"] : render_state["buff_offset"] + frame_size
                ]
                st_LED.show_all()
                render_state["render_count"] += 1
                render_state["buff_offset"] += frame_size
            
            next_tick_us += interval_us
        else:
            time.sleep_us(500)
# Core0_worker.py
import time, gc, machine
from lib.sys_bus import bus
from lib.net_bus import NetBus
from action.stream_actions import is_streaming, get_mode, get_frame_count, reset_frame_count

def task_loop(app, config):
    # 1. 🚀 初始化網絡總線 (從原 main 遷移)
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, config["discovery_port"])
    stream_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-FAST")
    stream_bus.connect(None, config["stream_port"])

    # 2. 🚀 本地狀態與緩存
    get_ticks = time.ticks_ms
    diff_ticks = time.ticks_diff
    s = {
        "f_local": None, "is_playing": False, "has_next_frame": False,
        "next_frame_t": get_ticks(), "frame_count": 0,
        "last_report_t": get_ticks(), "last_hbeat": get_ticks()
    }
    
    # 獲取雙核 Buffer 服務
    hub = bus.get_service("pixel_stream")

    def on_connect_request(url):
        if not ctrl_bus.connected:
            parts = url.replace("ws://", "").split("/", 1)
            host = parts[0].split(":")[0]
            port = int(parts[0].split(":")[1]) if ":" in parts[0] else 80
            path = "/" + parts[1] if len(parts) > 1 else "/"
            ctrl_bus.connect(host, port, path=path)

    ctx_extra = {"on_connect": on_connect_request}
    print(f"📡 [Core 0] Business Worker Online | ID: {bus.slave_id}")

    try:
        while True:
            now = get_ticks()
            # --- A. 網絡輪詢 ---
            discovery_bus.poll(**ctx_extra)
            if ctrl_bus.connected: ctrl_bus.poll()
            stream_bus.poll()

            # --- B. 播放器邏輯 (核心 0 負責供應數據) ---
            if is_streaming():
                mode = get_mode()
                if mode == "local":
                    # 1. 打開文件
                    if not s["is_playing"]:
                        try:
                            s["f_local"] = open('data.bin', 'rb')
                            s["is_playing"] = True
                            s["next_frame_t"] = now
                        except: s["is_playing"] = False
                    
                    # 2. 🚀 數據生產：讀取並提交到 Hub
                    if s["is_playing"] and diff_ticks(now, s["next_frame_t"]) >= 0:
                        view = hub.get_write_view()
                        if s["f_local"].readinto(view) == 0:
                            s["f_local"].seek(0)
                            s["f_local"].readinto(view)
                        
                        # 🚀 關鍵動作：提交給核心 1
                        hub.commit() 
                        
                        s["frame_count"] += 1
                        s["next_frame_t"] += config["local_fps_ms"]
                else:
                    # Direct 模式邏輯 (由 stream_actions 直接寫入 hub)
                    if s["is_playing"]:
                        if s["f_local"]: s["f_local"].close()
                        s["f_local"] = None
                        s["is_playing"] = False
                    s["frame_count"] = get_frame_count()
            
            # --- C. 系統報告 ---
            if diff_ticks(now, s["last_hbeat"]) > config["heartbeat_interval"]:
                elapsed = diff_ticks(now, s["last_report_t"])
                fps = (s["frame_count"] * 1000) / elapsed if elapsed > 0 else 0
                print(f"📊 [Core 0] NetIn FPS: {fps:.2f} | RAM: {gc.mem_free()//1024}KB")
                s.update({"last_hbeat": now, "last_report_t": now, "frame_count": 0})
                if get_mode() != "local": reset_frame_count()
                gc.collect()

            time.sleep_ms(config["refresh_rate_ms"])
    finally:
        if s["f_local"]: s["f_local"].close()
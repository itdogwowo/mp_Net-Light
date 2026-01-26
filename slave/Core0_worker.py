# Core0_worker.py
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus

def task_loop(app, config):
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    stream_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-FAST")
    discovery_bus.connect(None, config["discovery_port"])
    stream_bus.connect(None, config["stream_port"])

    def on_connect_request(url):
        if not ctrl_bus.connected:
            try:
                parts = url.replace("ws://", "").split("/", 1)
                hp = parts[0].split(":")
                h, p = hp[0], (int(hp[1]) if len(hp) > 1 else 80)
                path = "/" + parts[1] if len(parts) > 1 else "/"
                ctrl_bus.connect(h, p, path=path)
            except: pass

    ctx_extra = {"app": app, "on_connect": on_connect_request}
    
    # --- 供應鏈狀態 ---
    last_report = time.ticks_ms()
    s = {"f_local": None, "last_hb": time.ticks_ms()}
    hub = bus.get_service("pixel_stream")

    print("🚀 [Core 0] Data Router Active")
    while bus.shared.get("engine_run", True):
        # 1. 網路輪詢 (Data 路由)
        discovery_bus.poll(**ctx_extra)
        if ctrl_bus.connected: ctrl_bus.poll()
        stream_bus.poll()

        # 2. 🚀 生產者供應鏈邏輯 (由 Core 0 定時處理補貨)
        from action.stream_actions    import handle_supply_chain
        from action.heartbeat_actions import send_heartbeat
        from action.status_actions    import on_status_get
        # 傳入當前 ctrl_bus 供 Action 回報 Ready 信號
        worker_ctx = {"app": app, "send": ctrl_bus.write}
        handle_supply_chain(hub, s, worker_ctx)

        # 3. 系統維護
        now = time.ticks_ms()
        if time.ticks_diff(now, s["last_hb"]) > config["heartbeat_interval"]:
            if bus.shared.get("is_streaming") and ctrl_bus.connected:
                
                send_heartbeat({"app": app, "send": ctrl_bus.write})
                
                on_status_get({"app": app, "send": ctrl_bus.write}, {"query_type": 1})
            gc.collect()
            s["last_hb"] = now
            last_report = now
        time.sleep_ms(config.get("refresh_rate_ms", 1))
    
    ctrl_bus.disconnect()
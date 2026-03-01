# Core0_worker.py
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus
from app import App
def task_loop(app):
    # 初始化網路狀態追蹤器
    bus_sys = bus.shared["System"]
    
    # 獲取 NetworkManager 並讀取緩衝區大小
    nm = bus.get_service("network_manager")
    net_buf_size = getattr(nm, 'buffer_size', 16384) # 默認 16KB

    # 1. 啟動應用層 (App Layer)
    # 傳入 buffer_size，確保 FileRx 和 NetBus 共享同樣的緩衝策略
    app = App(buf_size=net_buf_size)

    # 2. 啟動網絡總線 (Transport Layer)
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS", buf_size=net_buf_size)
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCOVER", buf_size=2048) # UDP 保持小包
    discovery_bus.connect(None, bus_sys["discovery_port"])


    ctx_extra = {
        "app": app, 
        "ctrl_bus": ctrl_bus,
        "on_connect": lambda url: on_connect_request(ctrl_bus, url)
    }
    
    # --- 供應鏈狀態 ---
    last_report = time.ticks_ms()
    s = {"f_local": None, "last_hb": time.ticks_ms()}
    hub = bus.get_service("pixel_stream")

    print("🚀 [Core 0] Data Router Active")
    while bus.shared.get("engine_run", True):
        # 1. 網路守護：確保底層網路可用
        network_ok = nm.check_network() if nm else True
        if network_ok:
            try:
                discovery_bus.poll(**ctx_extra)
                if ctrl_bus.connected: 
                    ctrl_bus.poll()
            except Exception as e:
                # 預防網路突發中斷導致的 Socket 報錯
                print(f"📡 Network Poll Error: {e}")
        

        # 2. 🚀 生產者供應鏈邏輯 (由 Core 0 定時處理補貨)
        from action.stream_actions    import handle_supply_chain
        from action.heartbeat_actions import send_heartbeat
        from action.status_actions    import on_status_get
        # 傳入當前 ctrl_bus 供 Action 回報 Ready 信號
        worker_ctx = {"app": app, "send": ctrl_bus.write}
        handle_supply_chain(hub, s, worker_ctx)

        # 3. 系統維護
        now = time.ticks_ms()
        if time.ticks_diff(now, s["last_hb"]) > bus_sys["heartbeat_interval"]:
            if bus.shared.get("is_streaming") and ctrl_bus.connected:
                
                send_heartbeat({"app": app, "send": ctrl_bus.write})
                
                on_status_get({"app": app, "send": ctrl_bus.write}, {"query_type": 1})
            gc.collect()
            s["last_hb"] = now
            last_report = now
        time.sleep_ms(bus_sys.get("refresh_rate_ms", 1))
    
    ctrl_bus.disconnect()
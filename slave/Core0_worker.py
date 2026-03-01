# Core0_worker.py
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus

def check_network(lan, state):
    """
    優雅的網路檢查守護
    state: 傳入一個字典來記錄上一次的狀態，避免重複 print
    """
    is_connected = lan.isconnected()
    
    if is_connected and not state.get("was_connected", False):
        # 剛連上線
        ip_info = lan.ipconfig("addr4")
        print(f"🌐 LAN Connected! IP: {ip_info[0]}")
        state["was_connected"] = True
        state["retry_count"] = 0
        return True
        
    elif not is_connected:
        if state.get("was_connected", True):
            print("⚠️ LAN Disconnected! Attempting to recover...")
            state["was_connected"] = False
        
        # 這裡可以根據需要執行重新激活邏輯
        now = time.ticks_ms()
        if time.ticks_diff(now, state.get("last_retry", 0)) > 5000:
            lan.active(False)
            time.sleep_ms(100)
            lan.active(True)
            state["last_retry"] = now
            print("🔄 LAN Interface Reset...")
            
    return is_connected

def task_loop(app):
    # 初始化網路狀態追蹤器
    bus_sys = bus.shared["System"]
    net_state = {"was_connected": False, "last_retry": 0, "retry_count": 0}
    
    lan = bus.get_service("lan")
    
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, bus_sys["discovery_port"])

    # 🚀 Turbo Data Streamer (Port 8889)
    try:
        from lib.data_streamer import DataStreamer
        turbo = DataStreamer(port=8889)
        turbo.start()
        print("🚀 [Turbo] Service initialized on port 8889")
    except Exception as e:
        print(f"❌ [Turbo] Failed to init: {e}")
        turbo = None # 確保變量存在

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
        network_ok = check_network(lan, net_state)
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

        # 2.5 🚀 Turbo Data Streamer (Raw TCP)
        # 優先級高於系統維護
        busy = False
        if turbo:
            busy = turbo.poll()

        # 3. 系統維護
        now = time.ticks_ms()
        if time.ticks_diff(now, s["last_hb"]) > bus_sys["heartbeat_interval"]:
            if bus.shared.get("is_streaming") and ctrl_bus.connected:
                
                send_heartbeat({"app": app, "send": ctrl_bus.write})
                
                on_status_get({"app": app, "send": ctrl_bus.write}, {"query_type": 1})
            gc.collect()
            s["last_hb"] = now
            last_report = now
        
        # 如果 Turbo 正在忙碌 (高速接收中)，則跳過 Sleep 以最大化吞吐
        if not busy:
            time.sleep_ms(bus_sys.get("refresh_rate_ms", 1))
    
    ctrl_bus.disconnect()
    if turbo: turbo.stop()
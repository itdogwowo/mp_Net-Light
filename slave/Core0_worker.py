# Core0_worker.py
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus
from action.sys_actions import on_connect_request
from lib.network_manager import NetworkManager

def task_loop(app):
    # 初始化網路狀態追蹤器
    bus_sys = bus.shared["System"]
    
    nm = bus.get_service("network_manager")
    if not nm:
        print("⚠️ NetworkManager not found in bus, creating new instance...")
        nm = NetworkManager(bus)
        nm.init_from_config()

    lan = bus.get_service("lan") # 兼容舊代碼引用 (如果需要)
    
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, bus_sys["discovery_port"])

    def on_connect_wrapper(url):
        # 嘗試連接並在成功時更新配置 (現在移至 sys_actions 處理)
        return on_connect_request(ctrl_bus, url)

    ctx_extra = {
        "app": app, 
        "ctrl_bus": ctrl_bus,
        "on_connect": on_connect_wrapper
    }
    
    tried_config_connect = False
    
    # --- 供應鏈狀態 ---
    last_report = time.ticks_ms()
    s = {"f_local": None, "last_hb": time.ticks_ms()}
    hub = bus.get_service("pixel_stream")

    print("🚀 [Core 0] Data Router Active")
    while bus.shared.get("engine_run", True):
        # 1. 網路守護：確保底層網路可用
        # 同步 ctrl_bus 狀態到 bus.shared 供 NetworkManager 參考
        # 邏輯: 只要 (WebSocket 連接) OR (手動 Keep-Alive) 為真，則視為 App 連接中
        bus.shared["app_connected"] = ctrl_bus.connected or bus.shared.get("manual_keep_alive", False)
        
        network_ok = nm.check_network()
        if network_ok:
            # 啟動時嘗試讀取配置並連接一次
            if not tried_config_connect and not ctrl_bus.connected:
                tried_config_connect = True
                m_ip = bus_sys.get("master_IP", "")
                m_port = bus_sys.get("master_port", 0)
                if m_ip and m_port:
                    print(f"🔄 Auto-Connecting to stored Master: {m_ip}:{m_port}")
                    # 必須附帶 slave_id 作為 path
                    full_url = f"ws://{m_ip}:{m_port}/ws/{bus.slave_id}"
                    if on_connect_wrapper(full_url):
                        print("✅ Auto-Connect Success!")
                    else:
                        print("⚠️ Auto-Connect Failed, waiting for discovery...")

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
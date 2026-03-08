# Core0_worker.py
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus
from action.sys_actions import on_connect_request
from lib.ConfigManager import cfg_manager
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
    
    # 🚀 註冊 ctrl_bus 到全局總線，供 Core 1 使用 (若啟用 decode_core=1)
    bus.register_service("ctrl_bus", ctrl_bus)
    
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, bus_sys["discovery_port"])

    def on_connect_wrapper(url):
        # 嘗試連接並在成功時更新配置
        res = on_connect_request(ctrl_bus, url)
        if res:
            try:
                parts = url.replace("ws://", "").split("/", 1)
                hp = parts[0].split(":")
                h = hp[0]
                p = int(hp[1]) if len(hp) > 1 else 80
                
                # 針對性無損更新
                if bus_sys.get("master_IP") != h:
                    bus_sys["master_IP"] = h
                    print(f"💾 Updating Master IP: {h}")
                    cfg_manager.save_from_bus(update_key="System.master_IP")
                    
                if bus_sys.get("master_port") != p:
                    bus_sys["master_port"] = p
                    print(f"💾 Updating Master Port: {p}")
                    cfg_manager.save_from_bus(update_key="System.master_port")
                
            except Exception as e:
                print(f"⚠️ Config update error: {e}")
        return res

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

    # 🚀 提升 UDP 緩衝區 (如果支持)
    # nm.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65535)

    print("🚀 [Core 0] Data Router Active")
    while bus.shared.get("engine_run", True):
        # 1. 網路守護：確保底層網路可用
        # 同步 ctrl_bus 狀態到 bus.shared 供 NetworkManager 參考
        # 邏輯: 只要 (WebSocket 連接) OR (手動 Keep-Alive) 為真，則視為 App 連接中
        bus.shared["app_connected"] = ctrl_bus.connected or bus.shared.get("manual_keep_alive", False)
        
        # 在 Turbo 模式下，我們假設網絡是好的，跳過耗時的檢查
        if not bus.shared.get("turbo_mode", False):
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
                    # if ctrl_bus.connected: 
                    #    ctrl_bus.poll()
                except Exception as e:
                    # 預防網路突發中斷導致的 Socket 報錯
                    print(f"📡 Network Poll Error: {e}")
        
        # 無論是否 Turbo，都要全力輪詢 ctrl_bus
        # 這是數據進入的主要通道 (Network -> Hub)
        if ctrl_bus.connected:
             try:
                 # poll 內部會自動判斷是否執行 process_ingress (依據 decode_core)
                 ctrl_bus.poll(ctrl_bus=ctrl_bus)
             except Exception as e:
                 pass

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
            # 在高速傳輸 (Turbo Mode) 時，跳過心跳回報以節省頻寬和 CPU
            # 或者減少回報頻率 (例如每 5 秒一次，而不是每 1 秒)
            if not bus.shared.get("turbo_mode", False):
                if bus.shared.get("is_streaming") and ctrl_bus.connected:
                    
                    send_heartbeat({"app": app, "send": ctrl_bus.write})
                    
                    on_status_get({"app": app, "send": ctrl_bus.write}, {"query_type": 1})
            
            # GC 是一個耗時操作，在高速傳輸時應該避免頻繁觸發
            # 只有當內存真的不足時才觸發，或者在 Turbo 模式下完全禁用自動 GC
            if not bus.shared.get("turbo_mode", False):
                gc.collect()
            
            s["last_hb"] = now
            last_report = now
        
        # Turbo 模式下減少 sleep 時間，讓網路棧跑得更快
        if bus.shared.get("turbo_mode", False):
            time.sleep_ms(0) # Yield CPU but return ASAP
        else:
            time.sleep_ms(bus_sys.get("refresh_rate_ms", 1))
    
    ctrl_bus.disconnect()
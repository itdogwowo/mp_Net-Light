# Core0_worker.py (極簡版本)
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus

def check_network(lan, state):
    """網路檢查 (簡化版)"""
    is_connected = lan.isconnected()
    
    if is_connected and not state.get("was_connected"):
        ip_info = lan.ipconfig("addr4")
        print(f"🌐 LAN: {ip_info[0]}")
        state["was_connected"] = True
    
    elif not is_connected and state.get("was_connected"):
        print("⚠️ LAN Lost")
        state["was_connected"] = False
    
    return is_connected

def on_connect_request(ctrl_bus, url):
    """處理連接請求"""
    parts = url.split('/')
    if len(parts) >= 2:
        host = parts[0]
        port = int(parts[1])
        path = '/' + '/'.join(parts[2:]) if len(parts) > 2 else '/ws'
        ctrl_bus.connect(host, port, path)

def task_loop(app):
    """CPU 0 主循環 - 極簡版本"""
    
    bus_sys = bus.shared["System"]
    net_state = {}
    
    lan = bus.get_service("lan")
    
    # 初始化網絡總線
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, bus_sys["discovery_port"])
    
    # 保存引用
    bus.shared["ctrl_bus_ref"] = ctrl_bus
    
    ctx_extra = {
        "app": app,
        "ctrl_bus": ctrl_bus,
        "on_connect": lambda url: on_connect_request(ctrl_bus, url)
    }
    
    # 🔥 關鍵: 文件傳輸期間禁用其他任務
    s = {
        "f_local": None,
        "last_hb": time.ticks_ms(),
        "last_gc": time.ticks_ms()
    }
    
    hub = bus.get_service("pixel_stream")
    
    print("🚀 [Core 0] Active")
    
    while bus.shared.get("engine_run", True):
        # ========== 檢查是否在文件傳輸中 ==========
        rx_state = bus.shared.get("file_rx_state")
        is_file_transfer = (rx_state and rx_state.get("active"))
        
        # ========== 網路處理 (永遠執行) ==========
        if check_network(lan, net_state):
            try:
                discovery_bus.poll(**ctx_extra)
                
                if ctrl_bus.connected:
                    ctrl_bus.poll()  # 🔥 這裡處理所有消息
            
            except Exception as e:
                print(f"📡 Err: {e}")
        
        # ========== 流媒體任務 (文件傳輸時跳過) ==========
        if not is_file_transfer:
            from action.stream_actions import handle_supply_chain
            worker_ctx = {"app": app, "send": ctrl_bus.write}
            handle_supply_chain(hub, s, worker_ctx)
        
        # ========== 心跳維護 (降低頻率) ==========
        now = time.ticks_ms()
        
        if time.ticks_diff(now, s["last_hb"]) > bus_sys["heartbeat_interval"]:
            # 🔥 文件傳輸時跳過心跳
            if not is_file_transfer:
                if bus.shared.get("is_streaming") and ctrl_bus.connected:
                    from action.heartbeat_actions import send_heartbeat
                    from action.status_actions import on_status_get
                    
                    send_heartbeat({"app": app, "send": ctrl_bus.write})
                    on_status_get({"app": app, "send": ctrl_bus.write}, {"query_type": 1})
            
            s["last_hb"] = now
        
        # ========== GC 控制 (降低頻率) ==========
        if time.ticks_diff(now, s["last_gc"]) > 5000:  # 5 秒一次
            gc.collect()
            s["last_gc"] = now
        
        # 🔥 極短休眠
        time.sleep_ms(1)
    
    ctrl_bus.disconnect()
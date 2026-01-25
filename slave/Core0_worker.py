# Core0_worker.py
import time
import gc
from lib.sys_bus import bus
from lib.net_bus import NetBus

def task_loop(app, config):
    # 1. 🚀 完全比照你的舊代碼初始化順序與物件
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    stream_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-FAST")

    discovery_bus.connect(None, config["discovery_port"])
    stream_bus.connect(None, config["stream_port"])

    # 2. 連接請求解析
    def on_connect_request(url):
        if not ctrl_bus.connected:
            try:
                parts = url.replace("ws://", "").split("/", 1)
                hp = parts[0].split(":")
                h, p = hp[0], (int(hp[1]) if len(hp) > 1 else 80)
                path = "/" + parts[1] if len(parts) > 1 else "/"
                ctrl_bus.connect(h, p, path=path)
            except: pass

    # 3. 🚀 關鍵修復：我們不透過 poll 傳 send，我們讓 ctx 攜帶 bus 對象本身
    # 這樣 dispatcher 就能動態獲取發送途徑
    last_hb = time.ticks_ms()
    print("🚀 [Core 0] Data Router Active")

    while bus.shared.get("engine_run", True):
        # --- 路由工作 ---
        
        # 傳入 ctx_extra 供 discovery 使用
        discovery_bus.poll(on_connect=on_connect_request)
        
        if ctrl_bus.connected:
            ctrl_bus.poll()
            
        stream_bus.poll()

        # --- 系統維護 (Heartbeat) ---
        now = time.ticks_ms()
        if time.ticks_diff(now, last_hb) > config["heartbeat_interval"]:
            if ctrl_bus.connected:
                from action.heartbeat_actions import send_heartbeat
                # 🚀 這裡的手動發送，ctx 必須正確
                # 假設 NetBus 內部發送方法是 send_packet
                send_path = getattr(ctrl_bus, 'send_packet', getattr(ctrl_bus, 'send', None))
                send_heartbeat({"app": app, "send": send_path})
            gc.collect()
            last_hb = now

        time.sleep_ms(config.get("refresh_rate_ms", 1))

    ctrl_bus.disconnect()
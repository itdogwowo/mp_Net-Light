# Core0_worker.py
import time, gc
from lib.sys_bus import bus
from lib.net_bus import NetBus

def task_loop(app, config):
    """
    核心 0：數據路由與供應鏈調度中心
    職責：網路 I/O、Action 路由、FPS 結算、自動健康匯報
    """
    # 1. 網路總線初始化 (比照舊代碼穩定順序)
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    stream_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-FAST")
    discovery_bus.connect(None, config["discovery_port"])
    stream_bus.connect(None, config["stream_port"])

    # --- 性能結算引擎數據區 ---
    _metrics = {
        "last_render_total": 0,
        "last_net_total": 0,
        "current_render_fps": 0,
        "current_net_fps": 0,
        "last_tick": time.ticks_ms()
    }
    
    # 將結算後的速率註冊為 Provider，供 PC 分次查詢或自動回報使用
    bus.register_provider("fps_render", lambda: _metrics["current_render_fps"])
    bus.register_provider("fps_net", lambda: _metrics["current_net_fps"])
    
    # 2. 定義連線請求路由解析器 (URL 解析與 WS 橋接)
    def on_connect_request(url):
        if not ctrl_bus.connected:
            try:
                parts = url.replace("ws://", "").split("/", 1)
                hp = parts[0].split(":")
                h, p = hp[0], (int(hp[1]) if len(hp) > 1 else 80)
                path = "/" + parts[1] if len(parts) > 1 else "/"
                ctrl_bus.connect(h, p, path=path)
            except: pass

    # 封裝分發上下文
    ctx_extra = {"app": app, "on_connect": on_connect_request}
    
    # --- 生產與供應鏈狀態 ---
    hub = bus.get_service("pixel_stream")
    s = {"f_local": None}
    last_report = time.ticks_ms()

    print("🚀 [Core 0] Gateway Router Active | ID: {}".format(bus.slave_id))

    while bus.shared.get("engine_run", True):
        # I. 網路輪詢 (Inbound Data Parsing)
        discovery_bus.poll(**ctx_extra)
        if ctrl_bus.connected: 
            ctrl_bus.poll() # WS 會自動分發到 actions
        stream_bus.poll()

        # II. 數據供應鏈維護 (Producing to Hub)
        # 這裡從 Action 導入處理函數，實現 SD 卡預讀、檔案切換等邏輯
#         from action.stream_actions import handle_supply_chain
        # 傳遞 send 方法供 Action 回傳協定 ACK (如 STREAM_READY)
        worker_ctx = {"app": app, "send": ctrl_bus.write}
#         handle_supply_chain(hub, s, worker_ctx)

        # III. 實時性能結算 (每秒結算一次)
        now = time.ticks_ms()
        if time.ticks_diff(now, _metrics["last_tick"]) >= 1000:
            # 獲取來自 Core 1 寫入的總渲染幀數
            total_r = bus.get_data("render_total_count") or 0
            _metrics["current_render_fps"] = total_r - _metrics["last_render_total"]
            _metrics["last_render_total"] = total_r
            
            # 獲取 Core 0 網路層接收的總包數 (由 handle_supply_chain 更新)
            total_n = bus.shared.get("net_pkts_total", 0)
            _metrics["current_net_fps"] = total_n - _metrics["last_net_total"]
            _metrics["last_net_total"] = total_n
            
            _metrics["last_tick"] = now

        # IV. 定時主動回報 (Health Monitoring)
        # 每 10 秒將結算數據主動推送給 PC 控制端
        if time.ticks_diff(now, last_report) > 10000:
            if bus.shared.get("is_streaming") and ctrl_bus.connected:
                from action import status_actions
                # query_type: 1 代表僅回傳實時運行指標
                status_actions.on_status_get(worker_ctx, {"query_type": 1})
            
            # 定期執行 GC 避免堆內存碎片化
            gc.collect()
            last_report = now

        # 保持微小間隔，釋放 Python 直譯器給系統後台
        time.sleep_ms(config.get("refresh_rate_ms", 1))
    
    # V. 系統關閉處理
    ctrl_bus.disconnect()
    if s["f_local"]: s["f_local"].close()
    print("🔌 [Core 0] Gateway Router Shutdown.")
"""
Core 0 工作線程
═══════════════════════════════════════════════════════
職責:
- WebSocket 控制通道 (所有指令)
- UDP 廣播發現
- 指令分發
- FPS 統計
- 定時回報
"""
import time
import gc
from lib.sys_bus import bus
from lib.net_bus import NetBus

def task_loop(app, config):
    """
    Core 0 主循環
    ───────────────────────────────────────────────────
    參數:
        app: 應用實例
        config: 配置字典
    """
    print("🚀 [Core 0] Initializing Gateway Router...")
    
    # ══════════════════════════════════════════════════
    # 1. 網路總線初始化
    # ══════════════════════════════════════════════════
    
    # WebSocket 控制通道 (處理所有指令,包括 Stream 數據)
    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    
    # UDP 廣播發現
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, config.get("discovery_port", 9000))
    
    # 註冊 WebSocket send 到 bus.shared
    def ws_send_wrapper(data):
        if ctrl_bus.connected:
            ctrl_bus.write(data)
    
    bus.shared["ws_send"] = ws_send_wrapper
    bus.shared["app"] = app
    
    # ══════════════════════════════════════════════════
    # 2. 性能統計引擎
    # ══════════════════════════════════════════════════
    _metrics = {
        "last_render_total": 0,
        "last_net_total": 0,
        "current_render_fps": 0,
        "current_net_fps": 0,
        "last_tick": time.ticks_ms()
    }
    
    # 註冊 Provider
    bus.register_provider("fps_render", lambda: _metrics["current_render_fps"])
    bus.register_provider("fps_net", lambda: _metrics["current_net_fps"])
    
    # ══════════════════════════════════════════════════
    # 3. 連線請求處理器
    # ══════════════════════════════════════════════════
    def on_connect_request(url):
        """
        處理來自 DISCOVER 的 WebSocket 連線請求
        
        參數:
            url: "ws://192.168.1.100:8000/ws"
        """
        if not ctrl_bus.connected:
            try:
                # 解析 URL
                parts = url.replace("ws://", "").split("/", 1)
                hp = parts[0].split(":")
                host = hp[0]
                port = int(hp[1]) if len(hp) > 1 else 80
                path = "/" + parts[1] if len(parts) > 1 else "/"
                
                print(f"🔗 [Core 0] Connecting to {host}:{port}{path}")
                ctrl_bus.connect(host, port, path=path)
                
                if ctrl_bus.connected:
                    print(f"✅ [Core 0] Connected to Server")
            except Exception as e:
                print(f"❌ [Core 0] Connect Failed: {e}")
    
    # 封裝分發上下文
    ctx_extra = {
        "app": app,
        "on_connect": on_connect_request,
        "send": ws_send_wrapper
    }
    
    # ══════════════════════════════════════════════════
    # 4. 定時回報
    # ══════════════════════════════════════════════════
    last_report = time.ticks_ms()
    last_heartbeat = time.ticks_ms()
    
    print(f"🚀 [Core 0] Gateway Router Active | ID: {bus.slave_id}")
    
    # ══════════════════════════════════════════════════
    # 5. 主循環
    # ══════════════════════════════════════════════════
    while bus.shared.get("engine_run", True):
        # ─────────────────────────────────────────────
        # I. 網路輪詢
        # ─────────────────────────────────────────────
        
        # UDP 廣播發現
        discovery_bus.poll(**ctx_extra)
        
        # WebSocket 控制通道 (所有數據都從這裡來)
        if ctrl_bus.connected:
            ctrl_bus.poll(**ctx_extra)
        
        # ─────────────────────────────────────────────
        # II. 心跳發送 (每 10 秒)
        # ─────────────────────────────────────────────
        now = time.ticks_ms()
        
        if ctrl_bus.connected and time.ticks_diff(now, last_heartbeat) >= config.get("heartbeat_interval", 10000):
            try:
                from lib.proto import Proto
                from lib.schema_codec import SchemaCodec
                
                cmd_def = app.store.get(0x1201)  # HEARTBEAT
                if cmd_def:
                    payload = SchemaCodec.encode(cmd_def, {
                        "slave_id": bus.slave_id,
                        "uptime_ms": time.ticks_ms(),
                        "mem_free": gc.mem_free(),
                        "ws_connected": 1
                    })
                    ctrl_bus.write(Proto.pack(0x1201, payload))
            except:
                pass
            
            last_heartbeat = now
        
        # ─────────────────────────────────────────────
        # III. 性能結算 (每秒一次)
        # ─────────────────────────────────────────────
        if time.ticks_diff(now, _metrics["last_tick"]) >= 1000:
            # 獲取 Core 1 渲染總幀數
            total_r = bus.get_data("render_total_count") or 0
            _metrics["current_render_fps"] = total_r - _metrics["last_render_total"]
            _metrics["last_render_total"] = total_r
            
            # 獲取網路接收總包數
            total_n = bus.shared.get("net_pkts_total", 0)
            _metrics["current_net_fps"] = total_n - _metrics["last_net_total"]
            _metrics["last_net_total"] = total_n
            
            _metrics["last_tick"] = now
        
        # ─────────────────────────────────────────────
        # IV. 定時主動回報 (Health Monitoring)
        # ─────────────────────────────────────────────
        if time.ticks_diff(now, last_report) > 10000:  # 每 10 秒
            if bus.shared.get("is_streaming") and ctrl_bus.connected:
                try:
                    from action import status_actions
                    status_actions.on_status_get(ctx_extra, {"query_type": 1})
                except:
                    pass
            
            # 定期 GC
            gc.collect()
            last_report = now
        
        # ─────────────────────────────────────────────
        # V. 釋放 CPU
        # ─────────────────────────────────────────────
        time.sleep_ms(config.get("refresh_rate_ms", 1))
    
    # ══════════════════════════════════════════════════
    # 6. 系統關閉
    # ══════════════════════════════════════════════════
    print("🔌 [Core 0] Shutting down...")
    
    ctrl_bus.disconnect()
    discovery_bus.disconnect()
    
    print("🔌 [Core 0] Gateway Router Shutdown")
# /action/sys_actions.py
import machine, time
import gc
import os
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

# 定義常量 (直接使用數值)
CMD_DISCOVER = 0x1001
CMD_ANNOUNCE = 0x1002
CMD_SYS_INFO_GET = 0x1003

# --- 處理函數 (嚴格遵循 ctx, args 兩個參數) ---

def on_connect_request(bus_manager, url):
    """處理連接請求 (0x1002) 或來自 Discovery 的間接調用"""
    
    # 解析 ws://host:port/path
    parts = url.split("://")
    if len(parts) > 1:
        addr_part = parts[1]
    else:
        addr_part = parts[0]
        
    path_idx = addr_part.find("/")
    if path_idx != -1:
        path = addr_part[path_idx:]
        hp = addr_part[:path_idx]
    else:
        path = "/ws"
        hp = addr_part
        
    hp_parts = hp.split(":")
    h = hp_parts[0]
    p = int(hp_parts[1]) if len(hp_parts) > 1 else 80

    # 🚀 智能重連檢查：如果已經連到同一個目標，則忽略
    if bus_manager.connected:
        if bus_manager.host == h and bus_manager.port == p:
            # 已經連接到相同的 Host:Port，無需動作
            # print(f"ℹ️ [Network] Already connected to {h}:{p}, ignoring.")
            return True
            
        print(f"🔄 [Network] Connection change detected ({bus_manager.host}:{bus_manager.port} -> {h}:{p}), resetting...")
        bus_manager.disconnect()
        time.sleep_ms(50)
        
    return bus_manager.connect(h, p, path=path)

def on_discover(ctx, args):
    """
    在 Discovery 觸發時被調用
    ctx 應包含 app 及 ctrl_bus
    """
    ws_base = args.get("ws_url", "")
    if not ws_base: return
    
    slave_id = "".join(f"{b:02X}" for b in machine.unique_id())
    full_url = f"{ws_base.rstrip('/')}/{slave_id}"
    
    # 呼叫上面的重連函數
    # 從 ctx 中獲取 ctrl_bus 實例
    ctrl_bus = ctx.get("ctrl_bus")
    if ctrl_bus:
        on_connect_request(ctrl_bus, full_url)

def on_sys_info_get(ctx, args):
    """處理系統信息查詢 (0x1003)"""
    gc.collect()
    stat = os.statvfs('/')
    print(f"ℹ️ [Sys] Info Request - RAM Free: {gc.mem_free()//1024}KB, FS Free: {(stat[0]*stat[3])//1024}KB")
    # 這裡未來可以透過 ctx["send"] 回傳詳細 JSON 給 Server

def register(app):
    """註冊系統指令到分發器"""
    app.disp.on(CMD_DISCOVER, on_discover)
    app.disp.on(CMD_SYS_INFO_GET, on_sys_info_get)
    print("✅ [Action] Sys actions registered")
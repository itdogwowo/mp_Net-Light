# /action/sys_actions.py
import machine, time
import gc
import os
from lib.proto import Proto
from lib.schema_codec import SchemaCodec
from lib.sys_bus import bus
from lib.ConfigManager import cfg_manager

# 定義常量 (直接使用數值)
CMD_DISCOVER = 0x1001
CMD_ANNOUNCE = 0x1002
CMD_SYS_INFO_GET = 0x1003

# --- 處理函數 (嚴格遵循 ctx, args 兩個參數) ---

def on_connect_request(bus_manager, url):
    """
    處理連線請求
    bus_manager: 傳入 ctrl_bus 實例
    url: 完整的 ws://... 網址
    """
    try:
        # 1. 解析 URL
        parts = url.replace("ws://", "").split("/", 1)
        hp = parts[0].split(":")
        h = hp[0]
        p = int(hp[1]) if len(hp) > 1 else 80
        
        # 修正: 確保 path 正確解析
        if len(parts) > 1:
            path = "/" + parts[1]
        else:
            path = "/"

        # 2. 🚀 重連邏輯：如果已經在線，強制斷開
        if bus_manager.connected:
            # 檢查是否連到同一個目標
            # 如果 IP, Port 和 Path 都一樣，且連線狀態良好，則不需要重連
            # 注意: 這裡簡化檢查，如果已經連接且目標相同，直接返回 True
            # 但為了保證狀態同步，通常還是建議重連一次，或者至少發送一個 ping
            
            # 目前策略：總是重連以確保乾淨狀態
            print(f"🔄 [Network] Active connection detected, resetting for: {h}:{p}{path}")
            bus_manager.disconnect()
            time.sleep_ms(50) # 短暫休眠確保底層資源釋放
            
        # 3. 執行新連接
        # 注意: bus_manager.connect 內部的 settimeout(5) 會阻塞 Core0 少許時間
        # 但對於控制信道切換這是必要的。
        # 這裡呼叫 NetBus.connect(host, port, path)
        res = bus_manager.connect(h, p, path=path)

        if res:
             bus_sys = bus.shared["System"]
             # 針對性無損更新 
             if bus_sys.get("master_IP") != h: 
                 bus_sys["master_IP"] = h 
                 print(f"💾 Updating Master IP: {h}") 
                 cfg_manager.save_from_bus(update_key="System.master_IP") 
                 
             if bus_sys.get("master_port") != p: 
                 bus_sys["master_port"] = p 
                 print(f"💾 Updating Master Port: {p}") 
                 cfg_manager.save_from_bus(update_key="System.master_port")

        return res
        
    except Exception as e:
        print(f"❌ [sys_actions] Connect Error: {e}")
        return False

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
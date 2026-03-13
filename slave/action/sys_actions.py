# /action/sys_actions.py
import machine, time
import socket
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

FLAG_SYSTEM_ONLINE = 1 << 0
FLAG_CORE0_READY = 1 << 1
FLAG_CORE1_READY = 1 << 2
FLAG_FS_READY = 1 << 3
FLAG_WS_CONNECTED = 1 << 4
FLAG_APP_CONNECTED = 1 << 5

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
    server_ip = args.get("server_ip", "")
    if not ws_base:
        return

    slave_id = bus.slave_id
    if not slave_id or slave_id == "UNKNOWN":
        slave_id = "".join(f"{b:02X}" for b in machine.unique_id())
        bus.slave_id = slave_id

    full_url = f"{ws_base.rstrip('/')}/{slave_id}"
    _send_slave_announce(ctx, server_ip, slave_id)

    if bus.shared.get("system_online"):
        ctrl_bus = ctx.get("ctrl_bus")
        if ctrl_bus:
            on_connect_request(ctrl_bus, full_url)
        else:
            bus.shared["pending_connect_url"] = full_url
    else:
        bus.shared["pending_connect_url"] = full_url

def _ticks_ms():
    try:
        return time.ticks_ms()
    except Exception:
        return int(time.time() * 1000)

def _uptime_ms():
    try:
        return int(time.ticks_ms())
    except Exception:
        return int(time.time() * 1000)

def _build_online_snapshot(ctx):
    flags = 0
    system_online = bool(bus.shared.get("system_online", False))
    core0_ready = bool(bus.shared.get("core0_ready", False))
    core1_ready = bool(bus.shared.get("core1_ready", False))
    fs_ready = not bool(bus.shared.get("fs_scan_requested", False)) and not bool(bus.shared.get("fs_scan_done", False))
    ctrl_bus = ctx.get("ctrl_bus")
    ws_connected = bool(getattr(ctrl_bus, "connected", False)) if ctrl_bus else False
    app_connected = bool(bus.shared.get("app_connected", False))

    if system_online: flags |= FLAG_SYSTEM_ONLINE
    if core0_ready: flags |= FLAG_CORE0_READY
    if core1_ready: flags |= FLAG_CORE1_READY
    if fs_ready: flags |= FLAG_FS_READY
    if ws_connected: flags |= FLAG_WS_CONNECTED
    if app_connected: flags |= FLAG_APP_CONNECTED

    online = system_online and core0_ready and core1_ready and fs_ready
    status_msg = "ONLINE" if online else ("BOOTING" if core0_ready or core1_ready else "INIT")
    if system_online and not fs_ready:
        status_msg = "FS_SCANNING"
    if system_online and fs_ready and not core1_ready:
        status_msg = "WAIT_CORE1"
    if system_online and fs_ready and core1_ready and not ws_connected:
        status_msg = "WS_DISCONNECTED"

    return int(online), int(flags), int(_uptime_ms()), status_msg

def _send_slave_announce(ctx, server_ip, slave_id):
    if not server_ip:
        return False

    now_ms = _ticks_ms()
    last_ms = bus.shared.get("announce_last_ms", -999999)
    try:
        if time.ticks_diff(now_ms, last_ms) < 300:
            return True
    except Exception:
        if now_ms - last_ms < 300:
            return True
    bus.shared["announce_last_ms"] = now_ms

    app = ctx.get("app")
    if not app:
        return False

    cmd_def = app.store.get(CMD_ANNOUNCE)
    if not cmd_def:
        return False

    sys_cfg = bus.shared.get("System", {}) or {}
    pixel_count = int(sys_cfg.get("num_leds", 0) or 0) & 0xFFFF
    hw_version = str(sys_cfg.get("hw_version", "unknown"))

    online, flags, uptime_ms, status_msg = _build_online_snapshot(ctx)
    payload = {
        "slave_id": str(slave_id),
        "pixel_count": pixel_count,
        "hw_version": hw_version,
        "online": online,
        "flags": flags,
        "uptime_ms": uptime_ms,
        "status_msg": status_msg
    }

    try:
        pkt = Proto.pack(cmd=CMD_ANNOUNCE, payload=SchemaCodec.encode(cmd_def, payload))
    except Exception:
        return False

    port = int(sys_cfg.get("discovery_port", 9000) or 9000)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.sendto(pkt, (server_ip, port))
        finally:
            s.close()
        return True
    except Exception:
        return False

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

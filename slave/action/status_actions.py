# action/status_actions.py - STATUS 指令處理(修正版)
import json
import os
import gc
import time

# 全局系統狀態
SYSTEM_STATUS = {}
STATUS_FILE = "/system_status.json"

def load_system_status():
    """開機時載入 system_status.json"""
    global SYSTEM_STATUS
    
    try:
        with open(STATUS_FILE, 'r') as f:
            SYSTEM_STATUS = json.load(f)
        print("[Status] 已載入 system_status.json")
        print("[Status] 配置:", SYSTEM_STATUS)
    except OSError:
        # 文件不存在,創建默認配置
        SYSTEM_STATUS = {
            "server_ip": "0.0.0.0",
            "server_port": 8000,
            "auto_connect": False,
            "pixel_count": 400,
            "last_update": 0
        }
        save_system_status()
        print("[Status] 已創建默認 system_status.json")
    except Exception as e:
        print("[Status] 載入失敗: {}".format(e))
        SYSTEM_STATUS = {}

def save_system_status():
    """保存 system_status 到 JSON 文件"""
    try:
        with open(STATUS_FILE, 'w') as f:
            json.dump(SYSTEM_STATUS, f)
        print("[Status] 已保存 system_status.json")
        return True
    except Exception as e:
        print("[Status] 保存失敗: {}".format(e))
        return False

def get_runtime_status():
    """獲取實時系統狀態"""
    import network
    
    # 網絡信息
    try:
        lan = network.LAN()
        if lan.isconnected():
            ip, netmask, gateway, dns = lan.ifconfig()
        else:
            ip, netmask, gateway = "N/A", "N/A", "N/A"
    except:
        ip, netmask, gateway = "N/A", "N/A", "N/A"
    
    # 文件系統信息
    stat = os.statvfs('/')
    fs_total = (stat[0] * stat[2]) // 1024
    fs_free = (stat[0] * stat[3]) // 1024
    
    return {
        "uptime_ms": time.ticks_ms(),
        "mem_free": gc.mem_free(),
        "mem_alloc": gc.mem_alloc(),
        "fs_total_kb": fs_total,
        "fs_free_kb": fs_free,
        "network": {
            "connected": True,
            "ip": ip,
            "netmask": netmask,
            "gateway": gateway
        }
    }

# ==================== CMD Handlers ====================

def on_status_get(ctx, args):
    """處理 STATUS_GET 指令"""
    query_type = args.get("query_type", 0)
    
    print("[Status] STATUS_GET, query_type={}".format(query_type))
    
    result = {}
    
    if query_type == 0:
        result = SYSTEM_STATUS.copy()
    elif query_type == 1:
        result = get_runtime_status()
    elif query_type == 2:
        result = {
            "config": SYSTEM_STATUS.copy(),
            "runtime": get_runtime_status()
        }
    
    status_json = json.dumps(result)
    
    # 發送回應
    from lib.schema_loader import cmd_str_to_int
    from lib.schema_codec import encode_payload
    from lib.proto import pack_packet
    
    CMD_STATUS_RSP = cmd_str_to_int("0x1102")
    
    app = ctx.get("app")
    if not app:
        print("[Status] 錯誤: ctx 沒有 app")
        return
    
    cmd_def = app.store.get(CMD_STATUS_RSP)
    payload = encode_payload(cmd_def, {"status_json": status_json})
    packet = pack_packet(CMD_STATUS_RSP, payload)
    
    # 發送
    send_func = ctx.get("send") or ctx.get("send_loopback")
    if send_func:
        send_func(packet)
    
    print("[Status] 已發送 STATUS_RSP ({} bytes)".format(len(status_json)))

def on_status_update(ctx, args):
    """處理 STATUS_UPDATE 指令"""
    global SYSTEM_STATUS
    
    config_json = args.get("config_json", "{}")
    
    print("[Status] STATUS_UPDATE")
    print("[Status] 新配置: {}".format(config_json[:100]))
    
    success = 0
    message = ""
    
    try:
        new_config = json.loads(config_json)
        SYSTEM_STATUS.update(new_config)
        SYSTEM_STATUS["last_update"] = time.time()
        
        if save_system_status():
            success = 1
            message = "Status updated successfully"
            print("[Status] 更新成功")
        else:
            message = "Failed to save status file"
            print("[Status] 保存失敗")
    except Exception as e:
        message = str(e)
        print("[Status] 更新失敗: {}".format(e))
    
    # 發送 ACK
    from lib.schema_loader import cmd_str_to_int
    from lib.schema_codec import encode_payload
    from lib.proto import pack_packet
    
    CMD_STATUS_UPDATE_ACK = cmd_str_to_int("0x1104")
    
    app = ctx.get("app")
    if not app:
        print("[Status] 錯誤: ctx 沒有 app")
        return
    
    cmd_def = app.store.get(CMD_STATUS_UPDATE_ACK)
    payload = encode_payload(cmd_def, {
        "success": success,
        "message": message
    })
    packet = pack_packet(CMD_STATUS_UPDATE_ACK, payload)
    
    send_func = ctx.get("send") or ctx.get("send_loopback")
    if send_func:
        send_func(packet)
    
    print("[Status] 已發送 STATUS_UPDATE_ACK")

# ==================== 註冊 ====================

def register(app):
    """註冊 STATUS 指令"""
    from lib.schema_loader import cmd_str_to_int
    
    CMD_STATUS_GET = cmd_str_to_int("0x1101")
    CMD_STATUS_UPDATE = cmd_str_to_int("0x1103")
    
    app.disp.on(CMD_STATUS_GET, on_status_get)
    app.disp.on(CMD_STATUS_UPDATE, on_status_update)
    
    print("[Status] STATUS 指令已註冊")
    
    # 開機時載入 system_status
    load_system_status()
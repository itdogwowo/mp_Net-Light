# action/status_actions.py
import json
import gc
import os
import time
import machine, ubinascii
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

# 引用其他模組的狀態
from action import stream_actions

def get_runtime_info():
    """抓取整合性的實時運行數據"""
    # 獲取文件系統空間
    fs_stat = os.statvfs('/')
    fs_free = (fs_stat[0] * fs_stat[3]) // 1024
    uid = ubinascii.hexlify(machine.unique_id()).decode().upper()
    
    return {
        "id": uid,
        "mem_free": gc.mem_free(),
        "uptime_ms": time.ticks_ms(),
        "fs_free_kb": fs_free,
        # 🚀 整合 Stream 模組的實時數據
        "fps": stream_actions._STREAM_STATE["fps"],
        "frame_count": stream_actions.get_frame_count(),
        "stream_mode": stream_actions.get_mode(),
        "is_streaming": stream_actions.is_streaming()
    }

def on_status_get(ctx, args):
    """處理 PC 的 0x1101 指令"""
    app = ctx.get("app")
    query_type = args.get("query_type", 0)
    
    print(f"🔍 [Status] Active query received (type: {query_type})")
    
    # 根據 query_type 返回不同層級的數據
    if query_type == 1: # 僅實時數據 (Health Check)
        res_data = get_runtime_info()
    else: # 默認包含靜態配置 (需自行讀取 system_status.json)
        res_data = {"runtime": get_runtime_info(), "ver": "1.0.0"}
        
    try:
        status_json = json.dumps(res_data)
        cmd_def = app.store.get(0x1102) # STATUS_RSP
        payload = SchemaCodec.encode(cmd_def, {"status_json": status_json})
        packet = Proto.pack(0x1102, payload)
        
        if "send" in ctx:
            ctx["send"](packet)
            print("📤 [Status] Detailed health data sent")
    except Exception as e:
        print(f"❌ [Status] Error: {e}")

def register(app):
    """註冊狀態與健康查詢指令"""
    app.disp.on(0x1101, on_status_get)
    # 你可以選擇在這裡也載入配置檔
    print("✅ [Action] Status & Health actions integrated")
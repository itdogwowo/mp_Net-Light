# /action/sys_actions.py
import machine
import gc
import os
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

# 定義常量 (直接使用數值)
CMD_DISCOVER = 0x1001
CMD_ANNOUNCE = 0x1002
CMD_SYS_INFO_GET = 0x1003

# --- 處理函數 (嚴格遵循 ctx, args 兩個參數) ---

def on_discover(ctx, args):
    app = ctx["app"]
    # 這裡的 args 來自 schema，包含 server_ip 和 ws_url
    ws_base = args.get("ws_url", "")
    
    if "on_connect" in ctx and ws_base:
        slave_id = "".join(f"{b:02X}" for b in machine.unique_id())
        # 這裡生成完整 URL 並傳回給 main.py 的回調
        full_url = f"{ws_base.rstrip('/')}/{slave_id}"
        ctx["on_connect"](full_url)

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
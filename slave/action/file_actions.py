# action/file_actions.py
from lib.proto import Proto
from lib.schema_codec import SchemaCodec
from lib.sys_bus import bus
import time
import gc

def get_free_psram():
    """獲取可用 PSRAM"""
    try:
        return gc.mem_free()
    except:
        return 0

def on_file_begin(ctx, args):
    """0x2001: 開始接收文件"""
    app = ctx["app"]
    
    if args.get("path", False):
        args['path'] = bus.get_service("data_Phat") + args['path']
    
    total_size = args["total_size"]
    
    free_psram = get_free_psram()
    usable_psram = int(free_psram * 0.8)
    
    print(f"📊 [File] Size: {total_size // 1024} KB")
    
    # 模式選擇
    if total_size <= usable_psram:
        mode = "BIG_BUFFER"
        print(f"✅ [File] BIG BUFFER")
        
        big_buffer = bytearray(total_size)
        big_buffer_view = memoryview(big_buffer)
        
        bus.register_service("file_big_buffer", big_buffer_view)
    
    else:
        mode = "ROLLING"
        print(f"⚠️ [File] ROLLING")
        
        from lib.buffer_hub import AtomicStreamHub
        chunk_size = 8192
        num_buffers = min(128, usable_psram // chunk_size)
        
        rolling_hub = AtomicStreamHub(size=chunk_size, num_buffers=num_buffers)
        bus.register_service("file_rolling_hub", rolling_hub)
    
    bus.shared["file_rx_state"] = {
        "active": True,
        "mode": mode,
        "file_id": args["file_id"],
        "path": args["path"],
        "total_size": total_size,
        "sha256": args["sha256"],
        "received": 0,
        "start_write": False,
        "write_done": False,
        "verify_ok": False,
        "final_sha": "",
        "error": ""
    }
    
    print(f"📂 [File] {args['path']}")

def on_file_chunk(ctx, args):
    """0x2002: 接收分片 - 極簡版本"""
    rx_state = bus.shared.get("file_rx_state")
    
    # 🔥 快速檢查
    if not rx_state or not rx_state.get("active"):
        return
    
    mode = rx_state["mode"]
    offset = args.get("offset", 0)
    data = args.get("data")
    
    if not data:
        return
    
    # ========== BIG BUFFER 模式 ==========
    if mode == "BIG_BUFFER":
        big_buffer_view = bus.get_service("file_big_buffer")
        
        if not big_buffer_view:
            return
        
        # 🔥 無 try-except，讓錯誤直接暴露
        data_len = len(data)
        
        # 🔥 直接賦值 (最快)
        big_buffer_view[offset : offset + data_len] = data
        
        # 更新進度
        rx_state["received"] = max(rx_state["received"], offset + data_len)
        
        # ✅ 立即回 ACK (無條件)
        app = ctx["app"]
        ack_def = app.store.get(0x2004)
        ack_data = SchemaCodec.encode(ack_def, {
            "file_id": args["file_id"],
            "offset": offset
        })
        ctx["send"](Proto.pack(0x2004, ack_data))
    
    # ========== ROLLING 模式 ==========
    elif mode == "ROLLING":
        pass  # 暫時不實現

def on_file_end(ctx, args):
    """0x2003: 結束接收"""
    rx_state = bus.shared.get("file_rx_state")
    
    if not rx_state:
        return
    
    # 發送接收完成通知
    app = ctx["app"]
    recv_def = app.store.get(0x2007)
    recv_data = SchemaCodec.encode(recv_def, {
        "file_id": args["file_id"],
        "received_bytes": rx_state["received"],
        "mode": 1 if rx_state["mode"] == "BIG_BUFFER" else 0
    })
    ctx["send"](Proto.pack(0x2007, recv_data))
    
    print(f"📡 [CPU0] RECEIVED ({rx_state['received'] // 1024} KB)")
    
    # 通知 CPU 1
    rx_state["start_write"] = True

def on_file_query(ctx, args):
    """0x2005: 查詢文件"""
    pass  # 保持空實現

def register(app):
    app.disp.on(0x2001, on_file_begin)
    app.disp.on(0x2002, on_file_chunk)
    app.disp.on(0x2003, on_file_end)
    app.disp.on(0x2005, on_file_query)
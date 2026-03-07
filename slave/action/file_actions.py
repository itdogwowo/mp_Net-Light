from lib.proto import Proto
from lib.schema_codec import SchemaCodec
import ubinascii
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub

def on_file_begin(ctx, args):
    app = ctx["app"]

    # 🚀 Online Stream Mode (Magic ID: 0xFFFF)
    if args.get("file_id") == 0xFFFF:
        # 1. 解析 Path 參數，直接作為 Service Name
        # 如果為空，預設使用 "pixel_stream"
        stream_path = args.get("path")
        if not stream_path:
            stream_path = "pixel_stream"
            
        # 2. 嘗試獲取或創建 Hub
        hub = bus.get_service(stream_path)
        if not hub:
            print(f"✨ Creating AtomicStreamHub for '{stream_path}'")
            # 默認 64KB * 256 = 16MB 緩衝 (利用 32MB 大內存優勢，提供超大緩衝區抗抖動)
            hub = AtomicStreamHub(65536, 256)
            bus.register_service(stream_path, hub)
            
        # 3. 判斷是否開啟 "極速消耗模式" (Benchmark)
        # 只要路徑中包含 "benchmark" 或 "test" 即觸發
        is_benchmark = "benchmark" in stream_path or "test" in stream_path
        
        # 如果是 RAM 測速模式，強制開啟 Turbo
        if "ram_test" in stream_path:
             is_benchmark = True
             
        bus.shared["turbo_mode"] = is_benchmark
        
        # 4. 廣播當前使用的 Stream Service 名稱，供 Core1 切換
        bus.shared["stream_service"] = stream_path
            
        # 5. 標記 App 進入流模式
        app.is_online_stream = True
        app.current_stream_hub = stream_path # 記住當前 Hub 名稱供 Chunk 使用
        
        bus.shared["is_streaming"] = True
        bus.shared["is_ready"] = True
        
        mode_str = "🔥 Benchmark Mode" if is_benchmark else "📡 Stream Mode"
        print(f"[{mode_str}] Begin -> Service: {stream_path}")
        return

    if args.get("path",False):
        args['path'] = bus.get_service("data_Phat") + args['path']

    ok = app.file_rx.begin(args)
    if ok: print(f"📂 [File] Start -> {app.file_rx.path}")

def on_file_chunk(ctx, args):
    app = ctx["app"]

    # 🚀 Online Stream Mode
    if getattr(app, "is_online_stream", False) and args.get("file_id") == 0xFFFF:
        # 使用 begin 階段解析出的 hub name
        hub_name = getattr(app, "current_stream_hub", "pixel_stream")
        hub = bus.get_service(hub_name)
        
        # Debug Print (僅打印前幾個包以免刷屏)
        # if args["offset"] == 0:
        #    print(f"🧩 [Chunk] First Packet! Off:{args['offset']} Len:{len(args['data'])} Hub:{hub_name}")

        if hub:
             # 嘗試寫入 Hub
             # 使用 write_from (內存拷貝)
             # 對於極限性能，如果數據已經在 buffer 中，其實可以不做拷貝 (Zero-Copy)
             # 但這需要 Hub 支援 swap buffer
             res = hub.write_from(args["data"])
             
             # Debug: 如果 Offset 0 失敗，打印詳細原因
             if args["offset"] == 0 and not res:
                 print(f"⚠️ [Chunk] Off:0 Write Fail (Buffer Full?) Fill:{hub.get_fill_level()}")

             if res:
                 # ACK: 在 Turbo 模式下，為了極限吞吐量，我們跳過 ACK 發送
                 # 除非是特定的同步點（例如每 100 個包確認一次，這裡暫時完全禁用以測極限）
                 # 正常的流式傳輸仍然需要 ACK 來進行流控
                 if not bus.shared.get("turbo_mode", False):
                     if "send" in ctx:
                        ack_def = app.store.get(0x2004)
                        ack_data = SchemaCodec.encode(ack_def, {
                            "file_id": args["file_id"],
                            "offset": args["offset"]
                        })
                        ctx["send"](Proto.pack(0x2004, ack_data))
             else:
                 # Buffer Full
                 # print(f"⚠️ [Stream] Drop chunk {args['offset']} (Buffer Full)")
                 pass
        else:
             print(f"❌ [Chunk] Hub '{hub_name}' not found!")
        return

    if app.file_rx.chunk(args):
        # 🚀 關鍵：每收到一包就回傳 ACK
        # 讓 PC 知道可以發下一包了
        if "send" in ctx:
            ack_def = app.store.get(0x2004)
            ack_data = SchemaCodec.encode(ack_def, {
                "file_id": args["file_id"],
                "offset": args["offset"]
            })
            ctx["send"](Proto.pack(0x2004, ack_data))

def on_file_end(ctx, args):
    app = ctx["app"]

    # 🚀 Online Stream Mode
    if getattr(app, "is_online_stream", False) and args.get("file_id") == 0xFFFF:
        app.is_online_stream = False
        bus.shared["is_streaming"] = False
        bus.shared["is_ready"] = False
        bus.shared["turbo_mode"] = False
        print(f"🏁 [File] Online Stream End")
        return

    # 執行校驗
    ok = app.file_rx.end(args)
    
    path = app.file_rx.path
    sha = app.file_rx.last_sha_hex # 拿到剛才計算的 hex
    
    if ok:
        # 🚀 現代化、正式的結尾打印
        print("-" * 40)
        print(f"🏁 [File] End Success: {path}")
        print(f"🔒 [SHA256] {sha}")
        print("-" * 40)
    else:
        err = app.file_rx.last_error
        print(f"❌ [File] End Failed: {err}")

def on_file_query(ctx, args):
    app = ctx["app"]
    path = args.get("path")
    
    exists = 0
    sha = b'\x00' * 32
    
    # 檢查文件是否存在
    try:
        import os
        # 使用 os.stat 檢查文件
        os.stat(path)
        exists = 1
        # 調用你現有的高性能流式校驗函數
        sha = app.file_rx.sha256_digest_stream_from_file(path)
        print(f"🔍 [Query] {path} exists, SHA: {ubinascii.hexlify(sha).decode()[:8]}...")
    except:
        print(f"🔍 [Query] {path} not found.")

    # 回傳結果
    if "send" in ctx:
        rsp_def = app.store.get(0x2006)
        rsp_data = SchemaCodec.encode(rsp_def, {
            "exists": exists,
            "sha256": sha,
            "path": path
        })
        ctx["send"](Proto.pack(0x2006, rsp_data))

def on_file_raw_begin(ctx, args):
    app = ctx["app"]
    
    # Check if we have ctrl_bus in ctx (passed from Core0_worker via poll)
    ctrl_bus = ctx.get("ctrl_bus")
    if not ctrl_bus:
        print("❌ [Raw] Cannot enter Raw Mode: ctrl_bus not found in context")
        return

    # 1. Parse Args
    stream_path = args.get("path")
    if not stream_path: stream_path = "pixel_stream"
    
    total_size = args.get("total_size", 0)
    
    # 2. Get Hub
    hub = bus.get_service(stream_path)
    if not hub:
        # Create Hub (Same as 0x2001)
        print(f"✨ Creating AtomicStreamHub for '{stream_path}' (Raw Mode)")
        # 3份 buffer，每份 64KB，總計 192KB
        # 這足夠緩衝，同時避免佔用過多連續內存導致碎片化
        hub = AtomicStreamHub(65536, 3) 
        bus.register_service(stream_path, hub)
    
    # 3. Enter Raw Mode on NetBus
    # This will hijack the socket for the next 'total_size' bytes
    ctrl_bus.enter_raw_mode(hub, total_size)
    
    # 4. Set Turbo Mode flags
    bus.shared["turbo_mode"] = True
    bus.shared["stream_service"] = stream_path
    app.is_online_stream = True
    bus.shared["is_streaming"] = True
    bus.shared["is_ready"] = True
    
    print(f"🔥 [Raw Mode] Activated for {total_size} bytes -> {stream_path}")

def register(app):
    app.disp.on(0x2001, on_file_begin)
    app.disp.on(0x2002, on_file_chunk)
    app.disp.on(0x2003, on_file_end)
    app.disp.on(0x2005, on_file_query)
    app.disp.on(0x2007, on_file_raw_begin)
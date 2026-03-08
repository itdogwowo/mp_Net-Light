from lib.proto import Proto
from lib.schema_codec import SchemaCodec
import ubinascii
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub

def on_file_begin(ctx, args):
    app = ctx["app"]

    # 🚀 Online Stream Mode (Magic ID: 0xFFFF -> Mode: 0xFF)
    if args.get("mode") == 0xFF:
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

    # 🚀 使用新的 FileRx.begin (返回 Hub 或 None)
    hub = app.file_rx.begin(args)
    
    if hub:
        # 註冊到 Bus 供監控或調試 (可選)
        file_hub_name = f"filerx_{args.get('path')}"
        bus.register_service(file_hub_name, hub)
        
        # 不需要手動 bind，因為 begin 內部已經設置了 self.hub
        app.current_file_hub = hub
        
        print(f"📂 [File] Start -> {app.file_rx.path} (Mode: {app.file_rx.mode})")
    else:
        print(f"❌ [File] Start Failed: {app.file_rx.last_error}")

def on_file_chunk(ctx, args):
    app = ctx["app"]

    # 🚀 Online Stream Mode (Check app flag)
    # 移除 file_id 檢查，只依賴 app 狀態
    if getattr(app, "is_online_stream", False):
        # ... (Existing Stream Logic) ...
        hub_name = getattr(app, "current_stream_hub", "pixel_stream")
        hub = bus.get_service(hub_name)
        if hub:
             res = hub.write_from(args.get("data", b""))
             if res:
                 if not bus.shared.get("turbo_mode", False):
                     if "send" in ctx:
                        ack_def = app.store.get(0x2004)
                        ack_data = SchemaCodec.encode(ack_def, {
                            "offset": args["offset"]
                        })
                        ctx["send"](Proto.pack(0x2004, ack_data))
        return
    
    # 🚀 Standard File Mode with Background Write
    # 檢查是否有綁定的 Hub
    file_hub = getattr(app, "current_file_hub", None)
    
    if file_hub and app.file_rx.active:
        # 嘗試將數據推入 Hub
        # Core 0 負責生產
        if file_hub.write_from(args.get("data", b"")):
            # 成功推入 Hub
            # 這裡我們需要觸發 Core 1 去消費吗？
            # Core 1 應該是在 main loop 中自動輪詢 file_rx.process_background_task()
            
            # 發送 ACK (Flow Control)
            # 只有當成功寫入 Hub 才發 ACK
            if "send" in ctx:
                ack_def = app.store.get(0x2004)
                ack_data = SchemaCodec.encode(ack_def, {
                    "offset": args["offset"]
                })
                ctx["send"](Proto.pack(0x2004, ack_data))
        else:
            # Hub 滿了！不發 ACK (Backpressure)
            # Master 會超時重傳，或者我們應該發一個 BUSY 信號？
            # 簡單起見，不發 ACK，讓 Master 等待
            # print(f"⚠️ [File] Hub Full, Backpressure on {args['offset']}")
            pass
        return

    # Fallback to Old Sync Mode (if no hub or hub fail)
    if app.file_rx.chunk(args):
        # 🚀 關鍵：每收到一包就回傳 ACK
        # 讓 PC 知道可以發下一包了
        if "send" in ctx:
            ack_def = app.store.get(0x2004)
            ack_data = SchemaCodec.encode(ack_def, {
                "offset": args["offset"]
            })
            ctx["send"](Proto.pack(0x2004, ack_data))

def on_file_end(ctx, args):
    app = ctx["app"]

    # 🚀 Online Stream Mode
    # 移除 file_id 檢查
    if getattr(app, "is_online_stream", False):
        app.is_online_stream = False
        bus.shared["is_streaming"] = False
        bus.shared["is_ready"] = False
        bus.shared["turbo_mode"] = False
        print(f"🏁 [File] Online Stream End")
        return

    # 執行校驗
    # 注意: 在 Hub 模式下，end 需要確保 Hub 中的數據已全部消費完
    # 但 file_rx.end 內部已經有 flush 機制嗎？
    # process_background_task 是異步的，這裡需要等待 Hub 空
    # 或者，FileRx.end 應該返回 "PENDING"？
    
    # 簡單起見，我們假設 Master 在發送 END 前會等待所有 ACK
    # 而我們只有在 Hub 寫入成功時才發 ACK，所以理論上 Hub 應該已經被消費得差不多了
    # 除非 Core 1 非常慢。
    
    # 強制執行一次消費循環以確保最後的數據被寫入
    app.file_rx.process_hub_data()
    
    # 關閉並執行校驗
    ok = app.file_rx.end(args)
    
    path = app.file_rx.path
    sha = app.file_rx.last_sha_hex 
    final_digest = app.file_rx.get_final_sha()
    
    # 如果是實時計算的 SHA，我們應該用實時的結果 (如果是校驗失敗，end() 會返回 False)
    if final_digest:
        sha = ubinascii.hexlify(final_digest).decode()
    
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
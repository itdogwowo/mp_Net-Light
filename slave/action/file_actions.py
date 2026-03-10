from lib.proto import Proto
from lib.schema_codec import SchemaCodec
import ubinascii
from lib.sys_bus import bus

def on_file_begin(ctx, args):
    app = ctx["app"]
    if args.get("path",False):
        args['path'] = bus.get_service("data_Phat") + args['path']

    ok = app.file_rx.begin(args)
    if ok: print(f"📂 [File] Start -> {app.file_rx.path}")

def on_file_chunk(ctx, args):
    app = ctx["app"]
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
    else:
        # ⚠️ 如果寫入失敗，打印原因方便調試
        print(f"⚠️ [File] Chunk Failed: Off={args.get('offset')} Err={app.file_rx.last_error}")

def on_file_end(ctx, args):
    app = ctx["app"]
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

        # 回覆最終狀態 (0x2006)
        if "send" in ctx:
            try:
                import os
                st = os.stat(path)
                size = st[6]
                sha_bytes = ubinascii.unhexlify(sha)

                rsp_def = app.store.get(0x2006)
                rsp_data = SchemaCodec.encode(rsp_def, {
                    "exists": 1,
                    "sha256": sha_bytes,
                    "size": size,
                    "path": path
                })
                ctx["send"](Proto.pack(0x2006, rsp_data))
                print(f"📤 [File] Sent Final SHA256 (0x2006)")
            except Exception as e:
                print(f"⚠️ [File] Failed to send final SHA: {e}")
    else:
        err = app.file_rx.last_error
        print(f"❌ [File] End Failed: {err}")

def on_file_query(ctx, args):
    app = ctx["app"]
    path = args.get("path")
    
    exists = 0
    sha = b'\x00' * 32
    size = 0
    
    # 檢查文件是否存在
    try:
        import os
        # 使用 os.stat 檢查文件
        st = os.stat(path)
        exists = 1
        size = st[6]
        # 調用你現有的高性能流式校驗函數
        sha = app.file_rx.sha256_digest_stream_from_file(path)
        print(f"🔍 [Query] {path} exists, Size: {size}, SHA: {ubinascii.hexlify(sha).decode()[:8]}...")
    except:
        print(f"🔍 [Query] {path} not found.")

    # 回傳結果
    if "send" in ctx:
        rsp_def = app.store.get(0x2006)
        rsp_data = SchemaCodec.encode(rsp_def, {
            "exists": exists,
            "sha256": sha,
            "size": size,
            "path": path
        })
        ctx["send"](Proto.pack(0x2006, rsp_data))

def on_file_read(ctx, args):
    app = ctx["app"]
    path = args.get("path")
    offset = args.get("offset", 0)
    length = args.get("length", 1024)
    full_path = path
    
    if path:
        full_path = bus.get_service("data_Phat") + path

    try:
        with open(full_path, "rb") as f:
            f.seek(offset)
            data = f.read(length)
            
        if "send" in ctx:
            rsp_def = app.store.get(0x2002)
            rsp_data = SchemaCodec.encode(rsp_def, {
                "file_id": 0,
                "offset": offset,
                "data": data
            })
            ctx["send"](Proto.pack(0x2002, rsp_data))
            print(f"📤 [File] Read Chunk: {full_path} Off:{offset} Len:{len(data)}")
    except Exception as e:
        print(f"❌ [File] Read Failed: {full_path} - {e}")
        # Send empty data to indicate error/eof if needed, or just silence
        if "send" in ctx:
             rsp_def = app.store.get(0x2002)
             rsp_data = SchemaCodec.encode(rsp_def, {
                "file_id": 0,
                "offset": offset,
                "data": b""
            })
             ctx["send"](Proto.pack(0x2002, rsp_data))

def on_file_delete(ctx, args):
    app = ctx["app"]
    path = args.get("path")
    
    if not path: return
    
    full_path = bus.get_service("data_Phat") + path
    
    import os
    try:
        # 嘗試判斷類型，優先當文件刪除
        try:
            st = os.stat(full_path)
            mode = st[0]
            if (mode & 0o170000) == 0o040000: # Directory
                os.rmdir(full_path)
                print(f"🗑️ [Delete] Directory removed: {path}")
            else: # File
                os.remove(full_path)
                print(f"🗑️ [Delete] File removed: {path}")
        except OSError as e:
            print(f"⚠️ [Delete] Stat/Remove failed: {e}")
            
    except Exception as e:
        print(f"❌ [Delete] Unexpected error: {e}")
        
    # 操作後查詢狀態並回傳 (復用 on_file_query 邏輯)
    on_file_query(ctx, {"path": path})

def register(app):
    app.disp.on(0x2001, on_file_begin)
    app.disp.on(0x2002, on_file_chunk)
    app.disp.on(0x2003, on_file_end)
    app.disp.on(0x2005, on_file_query)
    app.disp.on(0x2007, on_file_read)
    app.disp.on(0x2009, on_file_delete)
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

def register(app):
    app.disp.on(0x2001, on_file_begin)
    app.disp.on(0x2002, on_file_chunk)
    app.disp.on(0x2003, on_file_end)
    app.disp.on(0x2005, on_file_query)
    app.disp.on(0x2007, on_file_read)
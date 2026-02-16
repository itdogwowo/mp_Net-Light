from lib.proto import Proto
from lib.schema_codec import SchemaCodec
import ubinascii
def on_file_begin(ctx, args):
    app = ctx["app"]
    ok = app.file_rx.begin(args)
    if ok: print(f"📂 [File] Start -> {app.file_rx.path}")

def on_file_chunk(ctx, args):
    """
    接收文件數據塊
    🚀 高性能模式：移除每塊 ACK
    僅接收並寫入，依賴 TCP 保證順序與完整性。
    最終校驗由 FILE_END 負責。
    """
    ctx["app"].file_rx.chunk(args)


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
        
        # 發送最終 ACK (FILE_ACK 0x2004)
        if "send" in ctx:
            ack_def = app.store.get(0x2004)
            # 使用 -1 表示整數個文件已完成
            ack_data = SchemaCodec.encode(ack_def, {
                "file_id": args.get("file_id", 0),
                "offset": -1 
            })
            ctx["send"](Proto.pack(0x2004, ack_data))
    else:
        err = app.file_rx.last_error
        print(f"❌ [File] End Failed: {err}")
        # 發送失敗 ACK (可選，這裡暫不發送或發送錯誤碼)

def on_file_query(ctx, args):
    app = ctx["app"]
    
    # 獲取路徑
    root = bus.get_service("data_Phat")
    rel_path = args.get("path")
    if not rel_path: return
    
    path = root + rel_path
    
    exists = 0
    sha_bytes = b'\x00' * 32
    
    # 檢查文件是否存在
    try:
        import os
        # 使用 os.stat 檢查文件
        os.stat(path)
        exists = 1
        # 調用你現有的高性能流式校驗函數
        sha_bytes = app.file_rx.sha256_digest_stream_from_file(path)
        print(f"🔍 [Query] {path} exists, SHA: {ubinascii.hexlify(sha_bytes).decode()[:8]}...")
    except Exception as e:
        print(f"🔍 [Query] {path} not found or error: {e}")

    # 回傳結果
    if "send" in ctx:
        rsp_def = app.store.get(0x2006)
        rsp_data = SchemaCodec.encode(rsp_def, {
            "exists": exists,
            "sha256": sha_bytes,
            "path": rel_path # 回傳相對路徑
        })
        ctx["send"](Proto.pack(0x2006, rsp_data))

def register(app):
    app.disp.on(0x2001, on_file_begin)
    app.disp.on(0x2002, on_file_chunk)
    app.disp.on(0x2003, on_file_end)
    app.disp.on(0x2005, on_file_query)

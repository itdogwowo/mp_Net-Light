# /action/file_actions.py
import os
import gc
import json
import ubinascii
from lib.schema_codec import SchemaCodec, encode_payload
from lib.schema_loader import cmd_str_to_int
from lib.proto import Proto

# 指令常量定義
CMD_FS_TREE_GET = 0x1205
CMD_FS_TREE_RSP = 0x1206

def on_tree_get(ctx, args):
    """
    處理 CMD_FS_TREE_GET:
    1. 生成包含 SHA256 的 JSON 快照
    2. 將結構成為文本回傳（或之後透過 file_triplet 傳送）
    """
    path = args.get("path", "/")
    out_path = "/temp/fs.json"
    app = ctx["app"]
    print(f"🔍 [FS] Generating tree with SHA256 for: {path}")
    
    try:
        app.file_rx.get_fs_tree_and_save(path, out_path)
        
        # 讀取生成的 JSON 作為文本回傳 (注意：如果 JSON 極大，這裡建議改用 file_triplet 傳送)
        # 這裡示範原本的文本回傳邏輯
        with open(out_path, "r") as f:
            tree_txt = f.read()
        
        if "send" in ctx:
            rsp_def = app.store.get(CMD_FS_TREE_RSP)
            rsp_payload = SchemaCodec.encode(rsp_def, {
                "path": path, 
                "tree": tree_txt
            })
            ctx["send"](Proto.pack(CMD_FS_TREE_RSP, rsp_payload))
            
        print(f"✅ [FS] Tree saved to {out_path}")
        
    except Exception as e:
        print(f"❌ [FS] Tree failed: {e}")


def on_file_begin(ctx, args):
    app = ctx["app"]
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

def register(app):
    app.disp.on(0x2001, on_file_begin)
    app.disp.on(0x2002, on_file_chunk)
    app.disp.on(0x2003, on_file_end)
    app.disp.on(0x2005, on_file_query)
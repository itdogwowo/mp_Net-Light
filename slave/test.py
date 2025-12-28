# main.py
import os
import ubinascii

from lib.app import App
from lib.proto import pack_packet
from lib.schema_loader import cmd_str_to_int
from lib.schema_codec2 import encode_payload
from lib.file_rx import sha256_digest_stream_from_file
from lib.handlers_sys import get_machine_info


def make_test_file(path="/test_src.bin", size=131072):
    with open(path, "wb") as f:
        for i in range(size):
            f.write(bytes(((i * 7) & 0xFF,)))
    return path


def print_file_head(path: str, limit=1200):
    try:
        with open(path, "r") as f:
            s = f.read(limit)
        print(s)
        if os.stat(path)[6] > limit:
            print("...(省略，完整內容已保存在 %s)" % path)
    except Exception as e:
        print("無法讀取 %s: %s" % (path, e))


def main():
    print("=== mp_Net-Light 離線自測（無網路）===")

    print("\n[1] 取得自身狀態/資訊")
    info = get_machine_info()
    for k in info:
        print(" - %s: %s" % (k, info[k]))

    print("\n[2] 初始化 App（載入 /schema，註冊 handlers）")
    app = App(schema_dir="/schema")
    ctx = {"send_loopback": lambda pkt: app.on_rx_bytes(pkt, ctx=ctx)}

    # ------------------------------------------------------------
    # [3] FS_TREE（單包，人眼可讀）
    # ------------------------------------------------------------
    print("\n[3] 取得完整文件結構（FS_TREE_GET -> FS_TREE_RSP，離線 loopback）")
    CMD_FS_TREE_GET = cmd_str_to_int("0x1205")
    CMD_FS_TREE_RSP = cmd_str_to_int("0x1206")

    def h_fs_tree_rsp(_ctx, args):
        print("FS_TREE_RSP path =", args.get("path"))
        print("----- tree -----")
        print(args.get("tree", ""))
        print("--------------")

    app.disp.on(CMD_FS_TREE_RSP, h_fs_tree_rsp)

    tree_def = app.store.get(CMD_FS_TREE_GET)
    if tree_def:
        tree_payload = encode_payload(tree_def, {"path": "/", "max_depth": 10, "include_size": 1})
        app.on_rx_bytes(pack_packet(CMD_FS_TREE_GET, tree_payload), ctx=ctx)
    else:
        print("ERROR: schema 未找到 FS_TREE_GET，請檢查 /schema/fs.json")

    # ------------------------------------------------------------
    # [4] FS_SNAP_GET（完全統一：生成 /fs_snapshot.json → 用 FILE 三件套回傳到 /rx_snapshot.json）
    # ------------------------------------------------------------
    print("\n[4] 取得文件結構快照（FS_SNAP_GET -> 生成 /fs_snapshot.json -> 回傳 /rx_snapshot.json）")
    CMD_FS_SNAP_GET = cmd_str_to_int("0x1213")
    snap_def = app.store.get(CMD_FS_SNAP_GET)
    if not snap_def:
        print("ERROR: schema 未找到 FS_SNAP_GET，請檢查 /schema/fs.json")
    else:
        snap_payload = encode_payload(snap_def, {
            "path": "/",
            "out_path": "/fs_snapshot.json",
            "max_depth": 20,
            "include_size": 1
        })
        app.on_rx_bytes(pack_packet(CMD_FS_SNAP_GET, snap_payload), ctx=ctx)

        print("\n[4.1] /rx_snapshot.json（前 1200 字元）")
        print("----------")
        print_file_head("/rx_snapshot.json", limit=1200)
        print("----------")

    # ------------------------------------------------------------
    # [5] FILE 三件套：上傳/下載 loopback 測試
    # ------------------------------------------------------------
    print("\n[5] 生成測試檔案（模擬上傳來源）")
    src = make_test_file("/test_src.bin", size=131072)
    print("生成:", src, "size=", os.stat(src)[6])

    print("\n[6] 自己對自己『上傳』：用 FILE 三件套把 src 傳到 /rx.bin")
    CMD_FILE_BEGIN = cmd_str_to_int("0x2001")
    CMD_FILE_CHUNK = cmd_str_to_int("0x2002")
    CMD_FILE_END   = cmd_str_to_int("0x2003")

    dst = "/rx.bin"
    file_id = 1
    chunk_size = 1024

    sha = sha256_digest_stream_from_file(src, bufsize=2048)
    print("sha256(src)=", ubinascii.hexlify(sha).decode())
    total = os.stat(src)[6]

    begin_def = app.store.get(CMD_FILE_BEGIN)
    chunk_def = app.store.get(CMD_FILE_CHUNK)
    end_def = app.store.get(CMD_FILE_END)

    if not (begin_def and chunk_def and end_def):
        print("ERROR: schema 未找到 FILE_BEGIN/CHUNK/END，請檢查 /schema/file.json")
        return

    begin_payload = encode_payload(begin_def, {
        "file_id": file_id,
        "total_size": total,
        "chunk_size": chunk_size,
        "sha256": sha,
        "path": dst
    })
    app.on_rx_bytes(pack_packet(CMD_FILE_BEGIN, begin_payload), ctx=ctx)

    with open(src, "rb") as f:
        off = 0
        buf = bytearray(chunk_size)
        while True:
            try:
                n = f.readinto(buf)
            except AttributeError:
                data = f.read(chunk_size)
                n = len(data)
                if n:
                    buf[:n] = data
            if not n:
                break

            chunk_payload = encode_payload(chunk_def, {
                "file_id": file_id,
                "offset": off,
                "data": bytes(buf[:n])
            })
            app.on_rx_bytes(pack_packet(CMD_FILE_CHUNK, chunk_payload), ctx=ctx)
            off += n

    end_payload = encode_payload(end_def, {"file_id": file_id})
    app.on_rx_bytes(pack_packet(CMD_FILE_END, end_payload), ctx=ctx)

    print("\n[7] 驗證上傳結果：sha256(/rx.bin) == sha256(src)")
    sha2 = sha256_digest_stream_from_file(dst, bufsize=2048)
    print("sha256(rx) =", ubinascii.hexlify(sha2).decode())
    print("比對：", "一致(通過)" if sha2 == sha else "不一致(失敗)")

    print("\n[8] 『下載測試』：再把 /rx.bin 複製傳輸到 /dl.bin（等效測下載鏈路）")
    src2 = dst
    dst2 = "/dl.bin"
    file_id = 2

    sha_src2 = sha256_digest_stream_from_file(src2, bufsize=2048)
    total2 = os.stat(src2)[6]

    begin_payload = encode_payload(begin_def, {
        "file_id": file_id,
        "total_size": total2,
        "chunk_size": chunk_size,
        "sha256": sha_src2,
        "path": dst2
    })
    app.on_rx_bytes(pack_packet(CMD_FILE_BEGIN, begin_payload), ctx=ctx)

    with open(src2, "rb") as f:
        off = 0
        buf = bytearray(chunk_size)
        while True:
            try:
                n = f.readinto(buf)
            except AttributeError:
                data = f.read(chunk_size)
                n = len(data)
                if n:
                    buf[:n] = data
            if not n:
                break

            chunk_payload = encode_payload(chunk_def, {
                "file_id": file_id,
                "offset": off,
                "data": bytes(buf[:n])
            })
            app.on_rx_bytes(pack_packet(CMD_FILE_CHUNK, chunk_payload), ctx=ctx)
            off += n

    end_payload = encode_payload(end_def, {"file_id": file_id})
    app.on_rx_bytes(pack_packet(CMD_FILE_END, end_payload), ctx=ctx)

    sha_dl = sha256_digest_stream_from_file(dst2, bufsize=2048)
    print("sha256(dl) =", ubinascii.hexlify(sha_dl).decode())
    print("比對：", "一致(通過)" if sha_dl == sha_src2 else "不一致(失敗)")

    print("\n完成。")


main()
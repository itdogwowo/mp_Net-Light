# offline_manual_tester.py
# 手動離線測試器：pack -> (chunk) -> StreamParser -> compare
# 支援：
# - 任意 payload 測試（text / hex）
# - 檔案分包傳輸測試（chunk + 重組 + hash 比對）

import sys

from proto import pack_packet, StreamParser, ADDR_BROADCAST

# 你可以自行改 CMD
CMD_ECHO = 0x0101
CMD_FILE_CHUNK = 0x0201

MY_ADDR = 0x0002
SERVER_ADDR = 0x0001


def _to_bytes_from_user(s: str) -> bytes:
    """
    支援兩種輸入：
    1) text: hello
    2) hex:  01 02 0A FF  或 01020AFF（不含 0x）
    """
    s = s.strip()
    if not s:
        return b""

    # 使用者指定 hex 模式：以 "hex:" 開頭
    if s.startswith("hex:"):
        h = s[4:].strip().replace(" ", "")
        if len(h) % 2 != 0:
            raise ValueError("hex length must be even")
        return bytes(int(h[i:i+2], 16) for i in range(0, len(h), 2))

    # 自動判斷：如果只包含 0-9a-fA-F 與空格，且長度合理，就當 hex
    maybe_hex = s.replace(" ", "")
    if maybe_hex and all(c in "0123456789abcdefABCDEF" for c in maybe_hex) and (len(maybe_hex) % 2 == 0):
        # 你如果不想自動判斷，可刪掉這段，全部要求用 hex: 前綴
        return bytes(int(maybe_hex[i:i+2], 16) for i in range(0, len(maybe_hex), 2))

    # 預設當作 utf-8 text
    return s.encode("utf-8")


def chunk_bytes(data: bytes, chunk_size: int) -> list:
    """把 bytes 切成固定大小 chunks"""
    out = []
    for i in range(0, len(data), chunk_size):
        out.append(data[i:i+chunk_size])
    return out


def simulate_stream_delivery(packets: list, fragment_pattern=(1, 2, 5, 3, 8, 13, 21, 34)) -> list:
    """
    模擬 TCP 傳輸：把多個 packet 黏在一起後，再用不規則大小切碎
    回傳 chunks（每次 feed 的資料）
    """
    stream = b"".join(packets)

    chunks = []
    i = 0
    p = 0
    while i < len(stream):
        sz = fragment_pattern[p % len(fragment_pattern)]
        chunks.append(stream[i:i+sz])
        i += sz
        p += 1
    return chunks


def sha256_bytes(data: bytes) -> str:
    """MicroPython/CPython 兼容 sha256"""
    try:
        import hashlib
        return hashlib.sha256(data).hexdigest()
    except Exception:
        # 部分 MicroPython 可能沒有 hashlib（通常 ESP32 有）
        return ""


def test_echo_manual():
    print("\n=== [1] MANUAL ECHO TEST ===")
    print("輸入任意資料：")
    print("- 文字：hello")
    print("- hex：hex: 01 02 0A FF")
    user = input("data> ").strip()

    payload = _to_bytes_from_user(user)
    print("payload len =", len(payload))

    # pack -> packets
    pkt = pack_packet(CMD_ECHO, payload, src=SERVER_ADDR, dst=MY_ADDR)

    # 模擬拆包/黏包：這裡只有一包，但仍然把它切碎再餵 parser
    chunks = simulate_stream_delivery([pkt])

    parser = StreamParser(max_len=4096, accept_dst=MY_ADDR)

    got = None
    for c in chunks:
        parser.feed(c)
        for ver, src, dst, cmd, pl in parser.pop():
            got = (ver, src, dst, cmd, pl)

    if got is None:
        print("FAIL: parser did not output any frame")
        return

    ver, src, dst, cmd, pl = got
    ok = (cmd == CMD_ECHO and pl == payload)

    print("decoded cmd=0x%04X payload_len=%d" % (cmd, len(pl)))
    print("compare:", "PASS" if ok else "FAIL")
    if not ok:
        print("orig:", payload[:64])
        print("recv:", pl[:64])
    print("drop_bytes:", parser.drop_bytes)


def test_file_chunking():
    print("\n=== [2] FILE CHUNKING TEST ===")
    print("輸入檔案路徑（在 MicroPython 上請先把檔案放進板子 FS，例如 /test.bin）：")
    path = input("file> ").strip()
    if not path:
        print("skip")
        return

    # 讀檔（MicroPython 也可）
    with open(path, "rb") as f:
        data = f.read()

    total = len(data)
    print("file size:", total)

    chunk_size = input("區塊大小 (e.g. 256/512/1024) > ").strip()
    chunk_size = int(chunk_size) if chunk_size else 512

    # --- sender side: 將檔案切成多個「協議封包」
    packets = []
    # DATA 內我們放一個最小重組頭：offset(u32) + chunk_bytes
    # 這是「文件分包」最簡模型，仍然不改協議 header
    off = 0
    while off < total:
        chunk = data[off:off + chunk_size]
        # offset(u32 LE)
        off_le = (off & 0xFFFFFFFF).to_bytes(4, "little")
        payload = off_le + chunk
        pkt = pack_packet(CMD_FILE_CHUNK, payload, src=SERVER_ADDR, dst=MY_ADDR)
        packets.append(pkt)
        off += len(chunk)

    # --- transport simulation: 黏包後切碎（模擬 TCP）
    chunks = simulate_stream_delivery(packets)

    # --- receiver side: 用 StreamParser 解包，按 offset 重組
    parser = StreamParser(max_len=4096, accept_dst=MY_ADDR)
    rebuilt = bytearray(total)
    written = 0

    for c in chunks:
        parser.feed(c)
        for ver, src, dst, cmd, pl in parser.pop():
            if cmd != CMD_FILE_CHUNK:
                continue
            if len(pl) < 4:
                continue

            off = int.from_bytes(pl[0:4], "little")
            blk = pl[4:]
            end = off + len(blk)
            if end > total:
                print("WARN: chunk out of range off=%d len=%d" % (off, len(blk)))
                continue

            # 寫回重組 buffer
            rebuilt[off:end] = blk
            written += len(blk)

    ok = (bytes(rebuilt) == data)
    print("重建寫入位元組數:", written, "(註：如果重新發送，可能包含重複位元組)")
    print("比較:", "PASS" if ok else "FAIL")

    # hash 對比（如果 hashlib 可用）
    h1 = sha256_bytes(data)
    h2 = sha256_bytes(bytes(rebuilt))
    if h1 and h2:
        print("sha256 orig :", h1)
        print("sha256 rebuilt:", h2)

    print("丟棄位元組:", parser.drop_bytes)


def main():
    print("=== OFFLINE MANUAL TESTER (no network) ===")
    print("proto: SOF+VER+SRC+DST+CMD+LEN+DATA+CRC16")
    while True:
        print("\nSelect:")
        print("  1) 手動回顯測試（輸入資料 -> 打包 -> 解析 -> 比較）")
        print("  2) 文件分塊測試（檔案 -> 封包 -> 解析 -> 重建 -> 比較）")
        print("  3) 出口")
        sel = input("> ").strip()
        if sel == "1":
            test_echo_manual()
        elif sel == "2":
            test_file_chunking()
        elif sel == "3":
            print("bye")
            break
        else:
            print("unknown")
# /sin_table.bin
# MicroPython 有時 __name__ 判斷可用也可不用
main()
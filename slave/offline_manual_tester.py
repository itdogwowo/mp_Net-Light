# offline_manual_tester_cn.py
# 離線手動測試器（不使用網路）
# - 手動輸入資料：pack -> StreamParser -> compare
# - 檔案分包測試：file -> chunks -> packets -> StreamParser -> rebuild -> compare + sha256
# - 計時統計

import time
from proto import pack_packet, StreamParser

CMD_ECHO = 0x0101
CMD_FILE_CHUNK = 0x0201

MY_ADDR = 0x0002


def now_ms():
    """Get ms timestamp (MicroPython/CPython compatible)."""
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def ms_diff(t1, t0):
    """Get ms delta (MicroPython/CPython compatible)."""
    try:
        return time.ticks_diff(t1, t0)
    except AttributeError:
        return t1 - t0


def sha256_hex(data: bytes):
    """Return sha256 hex string, or None if hashlib not available."""
    try:
        import hashlib
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def input_to_bytes(s: str) -> bytes:
    """
    支援兩種輸入：
    1) 文字：hello
    2) 十六進位：hex: 01 02 0A FF  或 hex:01020AFF
    """
    s = s.strip()
    if not s:
        return b""

    if s.startswith("hex:"):
        h = s[4:].strip().replace(" ", "")
        if len(h) % 2 != 0:
            raise ValueError("十六進位長度必須為偶數")
        return bytes(int(h[i:i + 2], 16) for i in range(0, len(h), 2))

    return s.encode("utf-8")


def simulate_tcp_fragmentation(packets: list, pattern=(1, 2, 5, 3, 8, 13, 21, 34)) -> list:
    """
    模擬 TCP 拆包/黏包：
    - 先將多個 packet 串接成一條 byte stream
    - 再用不規則長度切碎，模擬 recv() 可能拿到任意片段
    """
    stream = b"".join(packets)

    chunks = []
    i = 0
    p = 0
    while i < len(stream):
        sz = pattern[p % len(pattern)]
        chunks.append(stream[i:i + sz])
        i += sz
        p += 1
    return chunks


def test_manual_echo():
    print("\n=== [1] 手動資料回環測試（打包 -> 解析 -> 比對）===")
    print("請輸入任意資料：")
    print("  - 文字範例：hello")
    print("  - 十六進位範例：hex: 01 02 0A FF")

    user = input("data> ").strip()
    try:
        payload = input_to_bytes(user)
    except Exception as e:
        print("輸入格式錯誤：%s" % e)
        return

    print("原始資料長度：%d bytes" % len(payload))

    # pack timing
    t0 = now_ms()
    pkt = pack_packet(CMD_ECHO, payload, addr=MY_ADDR)
    t1 = now_ms()

    # fragmentation
    chunks = simulate_tcp_fragmentation([pkt])

    # parse timing
    parser = StreamParser(max_len=4096, accept_addr=MY_ADDR)
    got = None

    t2 = now_ms()
    for c in chunks:
        parser.feed(c)
        for ver, addr, cmd, pl in parser.pop():
            got = (ver, addr, cmd, pl)
    t3 = now_ms()

    if got is None:
        print("結果：失敗（解析器沒有輸出任何封包）")
        print("丟棄位元組數（drop_bytes）：%d" % parser.drop_bytes)
        return

    ver, addr, cmd, pl = got
    ok = (cmd == CMD_ECHO and pl == payload)

    print("解包結果：ver=%d addr=0x%04X cmd=0x%04X payload_len=%d"
          % (ver, addr, cmd, len(pl)))

    print("資料比對：%s" % ("通過" if ok else "失敗"))
    print("丟棄位元組數（drop_bytes）：%d" % parser.drop_bytes)
    print("耗時：打包=%dms、解析=%dms、總計=%dms"
          % (ms_diff(t1, t0), ms_diff(t3, t2), ms_diff(t3, t0)))

    # sha256 (optional)
    h1 = sha256_hex(payload)
    h2 = sha256_hex(pl)
    if h1 and h2:
        print("SHA256（原始）：%s" % h1)
        print("SHA256（解包）：%s" % h2)
        print("SHA256比對：%s" % ("一致" if h1 == h2 else "不一致"))
    else:
        print("SHA256：此平台不可用（缺少 hashlib），已以 bytes 直接比對為準。")


def test_file_chunking_ram_rebuild():
    print("\n=== [2] 檔案分包測試（檔案 -> 多封包 -> 解析 -> 重組 -> 驗證）===")
    print("請輸入檔案路徑：")
    print("  - MicroPython 範例：/test.bin")
    print("  - CPython 範例：./test.bin")

    path = input("file> ").strip()
    if not path:
        print("未輸入檔案路徑，已取消。")
        return

    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        print("讀取檔案失敗：%s" % e)
        return

    total = len(data)
    print("檔案大小：%d bytes" % total)

    s = input("chunk_size（建議 256/512/1024）> ").strip()
    chunk_size = int(s) if s else 512

    # 1) packetize timing
    t0 = now_ms()

    packets = []
    off = 0
    while off < total:
        chunk = data[off:off + chunk_size]

        # payload format (minimal):
        # offset(u32 little-endian) + chunk_bytes
        off_le = (off & 0xFFFFFFFF).to_bytes(4, "little")
        payload = off_le + chunk

        packets.append(pack_packet(CMD_FILE_CHUNK, payload, addr=MY_ADDR))
        off += len(chunk)

    t1 = now_ms()

    print("封包數量：%d 包" % len(packets))
    print("耗時：封包化=%dms" % ms_diff(t1, t0))

    # 2) simulate TCP fragmentation
    chunks = simulate_tcp_fragmentation(packets)

    # 3) parse + rebuild (RAM)
    parser = StreamParser(max_len=4096, accept_addr=MY_ADDR)
    rebuilt = bytearray(total)
    written = 0

    t2 = now_ms()
    for c in chunks:
        parser.feed(c)
        for ver, addr, cmd, pl in parser.pop():
            if cmd != CMD_FILE_CHUNK:
                continue
            if len(pl) < 4:
                continue

            off = int.from_bytes(pl[0:4], "little")
            blk = pl[4:]
            end = off + len(blk)
            if end > total:
                print("警告：分包超出檔案範圍 off=%d len=%d（已忽略）" % (off, len(blk)))
                continue

            rebuilt[off:end] = blk
            written += len(blk)
    t3 = now_ms()

    # 4) verify timing
    t4 = now_ms()
    same = (bytes(rebuilt) == data)
    h1 = sha256_hex(data)
    h2 = sha256_hex(bytes(rebuilt))
    t5 = now_ms()

    print("重組寫入位元組數：%d（可能包含重複寫入）" % written)
    print("bytes 比對：%s" % ("通過" if same else "失敗"))

    if h1 and h2:
        print("SHA256（原始）：%s" % h1)
        print("SHA256（重組）：%s" % h2)
        print("SHA256比對：%s" % ("一致" if h1 == h2 else "不一致"))
    else:
        print("SHA256：此平台不可用（缺少 hashlib），已以 bytes 直接比對為準。")

    print("丟棄位元組數（drop_bytes）：%d" % parser.drop_bytes)
    print("耗時：解析+重組=%dms、驗證=%dms、總計=%dms"
          % (ms_diff(t3, t2), ms_diff(t5, t4), ms_diff(t5, t0)))


def main():
    print("=== 離線手動測試器（不使用網路）===")
    print("協議：SOF(2)=NL VER(1)=3 ADDR(2) CMD(2) LEN(2) DATA CRC16(2)")

    while True:
        print("\n請選擇功能：")
        print("  1) 手動資料回環測試（輸入資料 -> 打包 -> 解析 -> 比對）")
        print("  2) 檔案分包測試（檔案 -> 分包 -> 解析 -> 重組 -> 驗證）")
        print("  3) 離開")

        sel = input("> ").strip()
        if sel == "1":
            test_manual_echo()
        elif sel == "2":
            test_file_chunking_ram_rebuild()
        elif sel == "3":
            print("已離開。")
            break
        else:
            print("未知選項，請重新輸入。")


main()
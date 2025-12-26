# offline_manual_tester_cn.py
# 離線手動測試器（不使用網路）- VER=3 ADDR(2)
#
# 更新點：
# - 使用三件套 FILE_BEGIN/FILE_CHUNK/FILE_END
# - 所有 CMD 的 DATA 開頭固定 dst_addr(u16)
# - SHA256 使用 MicroPython 相容方式（digest + hexlify）
# - CRC16 已在 proto.py 加速（table）

import time
import binascii

from proto import pack_packet, StreamParser
from file_transfer import (
    FileRxSession,
    CMD_FILE_BEGIN, CMD_FILE_CHUNK, CMD_FILE_END,
    sha256_digest_stream_from_file,
)

# 手動 echo 測試用
CMD_ECHO = 0x0101

MY_ADDR = 0x0002


def now_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)

def ms_diff(t1, t0):
    try:
        return time.ticks_diff(t1, t0)
    except AttributeError:
        return t1 - t0


def sha256_hex_bytes(data: bytes):
    try:
        import hashlib
        h = hashlib.sha256(data)
        if hasattr(h, "hexdigest"):
            return h.hexdigest()
        return binascii.hexlify(h.digest()).decode()
    except Exception:
        return None


def input_to_bytes(s: str) -> bytes:
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


def get_file_size(path: str):
    try:
        import os
        st = os.stat(path)
        if isinstance(st, tuple):
            return st[6]
        return st.st_size
    except Exception:
        return None


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

    # 注意：依你的規則，所有 CMD 的 DATA 都要以 dst_addr(u16) 開頭
    dst_prefix = bytes((MY_ADDR & 0xFF, (MY_ADDR >> 8) & 0xFF))
    payload2 = dst_prefix + payload

    t0 = now_ms()
    pkt = pack_packet(CMD_ECHO, payload2, addr=MY_ADDR)
    t1 = now_ms()

    chunks = simulate_tcp_fragmentation([pkt])

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

    if len(pl) < 2:
        print("結果：失敗（payload 太短）")
        return

    dst_in_data = pl[0] | (pl[1] << 8)
    body = pl[2:]

    ok = (cmd == CMD_ECHO and dst_in_data == MY_ADDR and body == payload)

    print("解包結果：ver=%d addr=0x%04X cmd=0x%04X payload_len=%d"
          % (ver, addr, cmd, len(pl)))

    print("DATA.dst_addr=0x%04X" % dst_in_data)
    print("資料比對：%s" % ("通過" if ok else "失敗"))
    print("丟棄位元組數（drop_bytes）：%d" % parser.drop_bytes)
    print("耗時：打包=%dms、解析=%dms、總計=%dms"
          % (ms_diff(t1, t0), ms_diff(t3, t2), ms_diff(t3, t0)))

    h1 = sha256_hex_bytes(payload2)
    h2 = sha256_hex_bytes(pl)
    if h1 and h2:
        print("SHA256（原始payload）=%s" % h1)
        print("SHA256（解包payload）=%s" % h2)
        print("SHA256比對：%s" % ("一致" if h1 == h2 else "不一致"))
    else:
        print("SHA256：此平台不可用（缺少 hashlib/binascii）。")


def test_file_triplet_transfer():
    print("\n=== [2] 檔案傳輸三件套測試（BEGIN -> CHUNK -> END）===")
    print("請輸入來源檔案路徑：")
    print("  - MicroPython 範例：/sin_table.bin")
    print("  - CPython 範例：./sin_table.bin")

    src_path = input("file> ").strip()
    if not src_path:
        print("未輸入檔案路徑，已取消。")
        return

    total = get_file_size(src_path)
    if total is None:
        print("取得檔案大小失敗（無法 stat）。")
        return
    print("檔案大小：%d bytes" % total)

    s = input("chunk_size（建議 512/1024/2048）> ").strip()
    chunk_size = int(s) if s else 1024

    dst_path = input("接收端寫入路徑（預設 /rx.bin）> ").strip() or "/rx.bin"

    # file_id：離線測試用固定值即可
    file_id = 1

    # 計算來源檔 sha256 digest（32 bytes）
    print("正在計算來源檔 SHA256（串流）...")
    t_hash0 = now_ms()
    sha_src = sha256_digest_stream_from_file(src_path, bufsize=2048)
    t_hash1 = now_ms()
    print("SHA256（來源檔）=%s（耗時 %dms）" % (binascii.hexlify(sha_src).decode(), ms_diff(t_hash1, t_hash0)))

    # 準備 BEGIN/CHUNK/END 封包串
    t0 = now_ms()
    rx = FileRxSession(MY_ADDR)

    packets = []

    # BEGIN packet
    begin_payload = rx.build_begin_payload(
        dst_addr=MY_ADDR,
        file_id=file_id,
        total_size=total,
        chunk_size=chunk_size,
        sha256_digest32=sha_src,
        path=dst_path
    )
    packets.append(pack_packet(CMD_FILE_BEGIN, begin_payload, addr=MY_ADDR))

    # CHUNK packets (stream read)
    buf = bytearray(chunk_size)
    off = 0
    with open(src_path, "rb") as f:
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

            chunk_payload = rx.build_chunk_payload(
                dst_addr=MY_ADDR,
                file_id=file_id,
                offset=off,
                data=bytes(buf[:n])
            )
            packets.append(pack_packet(CMD_FILE_CHUNK, chunk_payload, addr=MY_ADDR))
            off += n

    # END packet
    end_payload = rx.build_end_payload(dst_addr=MY_ADDR, file_id=file_id)
    packets.append(pack_packet(CMD_FILE_END, end_payload, addr=MY_ADDR))

    t1 = now_ms()
    print("封包總數：%d 包（包含 BEGIN/END）" % len(packets))
    print("耗時：封包化=%dms" % ms_diff(t1, t0))

    # 模擬 TCP 拆包/黏包
    chunks = simulate_tcp_fragmentation(packets)

    # 接收端解析並執行 handler
    parser = StreamParser(max_len=4096, accept_addr=MY_ADDR)
    t2 = now_ms()

    begin_ok = False
    end_ok = False

    for c in chunks:
        parser.feed(c)
        for ver, addr, cmd, payload in parser.pop():
            # 所有 payload 皆以 dst_addr(u16) 開頭
            # 由 FileRxSession 內部再判斷是否 for me
            if cmd == CMD_FILE_BEGIN:
                begin_ok = rx.on_begin(payload)
            elif cmd == CMD_FILE_CHUNK:
                rx.on_chunk(payload)
            elif cmd == CMD_FILE_END:
                end_ok = rx.on_end(payload)

    t3 = now_ms()

    print("丟棄位元組數（drop_bytes）：%d" % parser.drop_bytes)
    print("耗時：解析+接收處理=%dms" % ms_diff(t3, t2))

    if not begin_ok:
        print("BEGIN：未成功（可能不是給我 / 格式錯誤 / 開檔失敗）")
        if rx.last_error:
            print("最後錯誤：%s" % rx.last_error)
        return

    if end_ok:
        print("END：SHA256 驗證通過")
        r = rx.last_result
        print("接收結果：")
        print("  path=%s" % r["path"])
        print("  total=%d written=%d" % (r["total"], r["written"]))
        print("  sha256_expect=%s" % r["sha256_expect"])
        print("  sha256_got   =%s" % r["sha256_got"])
    else:
        print("END：SHA256 驗證失敗")
        if rx.last_error:
            print("最後錯誤：%s" % rx.last_error)
        if rx.last_result:
            r = rx.last_result
            print("  sha256_expect=%s" % r["sha256_expect"])
            print("  sha256_got   =%s" % r["sha256_got"])

    print("總計耗時：%dms" % ms_diff(t3, t0))


def main():
    print("=== 離線手動測試器（不使用網路）===")
    print("協議：SOF(2)=NL VER(1)=3 ADDR(2) CMD(2) LEN(2) DATA CRC16(2)")
    print("規則：所有 CMD 的 DATA 固定以 dst_addr(u16) 開頭")

    while True:
        print("\n請選擇功能：")
        print("  1) 手動資料回環測試（輸入資料 -> 打包 -> 解析 -> 比對）")
        print("  2) 檔案三件套測試（BEGIN -> CHUNK -> END + SHA256驗證）")
        print("  3) 離開")

        sel = input("> ").strip()
        if sel == "1":
            test_manual_echo()
        elif sel == "2":
            test_file_triplet_transfer()
        elif sel == "3":
            print("已離開。")
            break
        else:
            print("未知選項，請重新輸入。")


main()
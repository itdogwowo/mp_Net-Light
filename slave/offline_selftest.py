# offline_selftest.py
# 完全離線測試：不使用網路，不使用 socket
# 測試目標：StreamParser 對於黏包/拆包/雜訊/CRC錯誤 的健壯性

from proto import pack_packet, StreamParser, ADDR_BROADCAST

# 測試用 CMD
CMD_PING = 0x0001
CMD_DATA = 0x1234

MY_ADDR = 0x0002
SERVER_ADDR = 0x0001


def hexdump(b: bytes, n=64):
    s = b[:n]
    return " ".join("{:02X}".format(x) for x in s) + (" ..." if len(b) > n else "")


def corrupt_one_byte(pkt: bytes, offset_from_end=1) -> bytes:
    """
    破壞封包：翻轉某個 byte（預設翻轉倒數第 1 個 byte）
    用於測試 CRC fail 時 parser 是否能 resync
    """
    if len(pkt) < 5:
        return pkt
    ba = bytearray(pkt)
    i = len(ba) - offset_from_end
    ba[i] ^= 0xFF
    return bytes(ba)


def chunk_bytes_deterministic(data: bytes, pattern=(1, 2, 5, 3, 8, 13, 21, 34)):
    """
    將資料切成碎片（不使用 random，MicroPython 一定能跑）
    pattern: 每片大小輪流使用這些數字
    """
    out = []
    i = 0
    p = 0
    while i < len(data):
        sz = pattern[p % len(pattern)]
        out.append(data[i:i + sz])
        i += sz
        p += 1
    return out


def main():
    print("=== OFFLINE StreamParser SELF TEST ===")

    # 1) 準備 parser：只接受 DST=MY_ADDR 或 broadcast 的包
    parser = StreamParser(max_len=4096, accept_dst=MY_ADDR)

    # 2) 建立幾個正常封包
    pkt1 = pack_packet(CMD_PING, b"hello", src=SERVER_ADDR, dst=MY_ADDR)
    pkt2 = pack_packet(CMD_DATA, b"\x01\x02\x03\x04\x05", src=SERVER_ADDR, dst=MY_ADDR)
    pkt3 = pack_packet(CMD_PING, b"broadcast_ping", src=SERVER_ADDR, dst=ADDR_BROADCAST)

    # 3) 建立一個「不屬於自己」的封包（DST=0x9999）
    pkt_not_mine = pack_packet(CMD_PING, b"should_be_ignored", src=SERVER_ADDR, dst=0x9999)

    # 4) 建立一個 CRC 壞掉的封包
    pkt_bad = corrupt_one_byte(pack_packet(CMD_DATA, b"crc_bad", src=SERVER_ADDR, dst=MY_ADDR), offset_from_end=2)

    # 5) 把它們混在一起：雜訊 + 黏包 + 壞包 + 非自己包 + 正常包
    noise1 = b"\x00\xFF\xAA\x55GARBAGE"
    noise2 = b"\x13\x37\x13\x37"

    stream = b"".join([
        noise1,
        pkt1, pkt2,               # 黏包：兩包連在一起
        noise2,
        pkt_bad,                  # 壞 CRC：parser 應該丟棄並 resync
        pkt_not_mine,             # DST 不符：parser 應該 consume 但不 yield
        pkt3,                     # broadcast：應該 yield
    ])

    print("Raw stream length:", len(stream))
    print("Raw stream hexdump:", hexdump(stream, 80))

    # 6) 將 stream 切碎，模擬 TCP 拆包/分段到達
    chunks = chunk_bytes_deterministic(stream)
    print("Chunks:", len(chunks), "example lens:", [len(chunks[i]) for i in range(min(10, len(chunks)))])

    # 7) 餵入 parser，收集解出的封包
    decoded = []
    for idx, c in enumerate(chunks):
        parser.feed(c)

        # pop() 可能吐出 0..N 包
        for ver, src, dst, cmd, payload in parser.pop():
            decoded.append((ver, src, dst, cmd, payload))
            print("[DECODED] ver=%d src=0x%04X dst=0x%04X cmd=0x%04X payload=%r"
                  % (ver, src, dst, cmd, payload))

    print("---")
    print("drop_bytes:", parser.drop_bytes)
    print("decoded frames:", len(decoded))

    # 8) 驗證：應該解到 pkt1、pkt2、pkt3（共 3 包）
    # pkt_bad 不應解出；pkt_not_mine 不應 yield
    assert len(decoded) == 3, "expected 3 decoded frames, got %d" % len(decoded)

    # 驗證內容
    assert decoded[0][3] == CMD_PING and decoded[0][4] == b"hello"
    assert decoded[1][3] == CMD_DATA and decoded[1][4] == b"\x01\x02\x03\x04\x05"
    assert decoded[2][3] == CMD_PING and decoded[2][4] == b"broadcast_ping"

    print("SELF TEST PASS")


if __name__ == "__main__":
    main()
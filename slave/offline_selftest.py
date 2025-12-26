# offline_selftest.py (VER=3 ADDR)
# 基礎：測 StreamParser 是否能處理雜訊/壞CRC/非目標addr/拆包黏包

from proto import pack_packet, StreamParser, ADDR_BROADCAST

CMD_PING = 0x0001
MY_ADDR = 0x0002

def corrupt_one_byte(pkt: bytes, offset_from_end=1) -> bytes:
    ba = bytearray(pkt)
    i = len(ba) - offset_from_end
    ba[i] ^= 0xFF
    return bytes(ba)

def chunk_bytes_deterministic(data: bytes, pattern=(1, 2, 5, 3, 8, 13, 21, 34)):
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
    print("=== OFFLINE StreamParser SELF TEST (VER=3 ADDR) ===")
    parser = StreamParser(max_len=4096, accept_addr=MY_ADDR)

    # 注意：依你規則，payload 也應該以 dst_addr(u16) 開頭
    dst_prefix = bytes((MY_ADDR & 0xFF, (MY_ADDR >> 8) & 0xFF))

    pkt1 = pack_packet(CMD_PING, dst_prefix + b"hello", addr=MY_ADDR)
    pkt2 = pack_packet(CMD_PING, dst_prefix + b"broadcast_ping", addr=ADDR_BROADCAST)
    pkt_not_mine = pack_packet(CMD_PING, dst_prefix + b"should_be_ignored", addr=0x9999)
    pkt_bad = corrupt_one_byte(pack_packet(CMD_PING, dst_prefix + b"crc_bad", addr=MY_ADDR), offset_from_end=2)

    noise = b"\x00\xFF\xAA\x55GARBAGE"

    stream = b"".join([noise, pkt1, pkt_bad, pkt_not_mine, pkt2])
    chunks = chunk_bytes_deterministic(stream)

    cnt = 0
    for c in chunks:
        parser.feed(c)
        for ver, addr, cmd, payload in parser.pop():
            cnt += 1

    print("decoded frames:", cnt)
    print("drop_bytes:", parser.drop_bytes)
    assert cnt == 2
    print("SELF TEST PASS")

main()
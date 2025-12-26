# offline_selftest.py
# 自動離線自測：雜訊 + 壞CRC + 非自己ADDR + 拆包/黏包

from proto import pack_packet, StreamParser, ADDR_BROADCAST

CMD_PING = 0x0001
CMD_DATA = 0x1234

MY_ADDR = 0x0002


def hexdump(b: bytes, n=64):
    s = b[:n]
    return " ".join("{:02X}".format(x) for x in s) + (" ..." if len(b) > n else "")


def corrupt_one_byte(pkt: bytes, offset_from_end=1) -> bytes:
    if len(pkt) < 5:
        return pkt
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

    pkt1 = pack_packet(CMD_PING, b"hello", addr=MY_ADDR)
    pkt2 = pack_packet(CMD_DATA, b"\x01\x02\x03\x04\x05", addr=MY_ADDR)
    pkt3 = pack_packet(CMD_PING, b"broadcast_ping", addr=ADDR_BROADCAST)

    pkt_not_mine = pack_packet(CMD_PING, b"should_be_ignored", addr=0x9999)
    pkt_bad = corrupt_one_byte(pack_packet(CMD_DATA, b"crc_bad", addr=MY_ADDR), offset_from_end=2)

    noise1 = b"\x00\xFF\xAA\x55GARBAGE"
    noise2 = b"\x13\x37\x13\x37"

    stream = b"".join([
        noise1,
        pkt1, pkt2,
        noise2,
        pkt_bad,
        pkt_not_mine,
        pkt3,
    ])

    print("Raw stream length:", len(stream))
    print("Raw stream hexdump:", hexdump(stream, 80))

    chunks = chunk_bytes_deterministic(stream)
    print("Chunks:", len(chunks), "example lens:", [len(chunks[i]) for i in range(min(10, len(chunks)))])

    decoded = []
    for c in chunks:
        parser.feed(c)
        for ver, addr, cmd, payload in parser.pop():
            decoded.append((ver, addr, cmd, payload))
            print("[DECODED] ver=%d addr=0x%04X cmd=0x%04X payload=%r"
                  % (ver, addr, cmd, payload))

    print("---")
    print("drop_bytes:", parser.drop_bytes)
    print("decoded frames:", len(decoded))

    assert len(decoded) == 3, "expected 3 decoded frames, got %d" % len(decoded)
    assert decoded[0][2] == CMD_PING and decoded[0][3] == b"hello"
    assert decoded[1][2] == CMD_DATA and decoded[1][3] == b"\x01\x02\x03\x04\x05"
    assert decoded[2][2] == CMD_PING and decoded[2][3] == b"broadcast_ping"

    print("SELF TEST PASS")


main()
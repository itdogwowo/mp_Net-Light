import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(root, "slave"))

from lib.proto import Proto, StreamParser, CUR_VER


def _collect(parser, data, chunk_sizes):
    i = 0
    mv = memoryview(data)
    for s in chunk_sizes:
        if i >= len(data):
            break
        parser.feed(mv[i : i + s])
        i += s
        for pkt in parser.pop():
            yield pkt
    if i < len(data):
        parser.feed(mv[i:])
        for pkt in parser.pop():
            yield pkt


def main():
    parser = StreamParser(max_len=65535)

    p1 = Proto.pack(0x1003, b"abc", addr=0xFFFF)
    p2 = Proto.pack(0x1003, b"defgh", addr=0x1234)
    parser.feed(p1 + p2)
    out = list(parser.pop())
    assert len(out) == 2
    assert out[0][0] == CUR_VER
    assert out[0][1] == 0xFFFF
    assert out[0][2] == 0x1003
    assert bytes(out[0][3]) == b"abc"
    assert out[1][0] == CUR_VER
    assert out[1][1] == 0x1234
    assert out[1][2] == 0x1003
    assert bytes(out[1][3]) == b"defgh"

    payload = (bytes(range(256)) * 300)[:65535]
    p = Proto.pack(0x2002, payload, addr=0x1234)
    parser = StreamParser(max_len=65535)
    out = list(_collect(parser, p, [1, 2, 3, 7, 11, 1024, 4096, 8192, 16384, 32768]))
    assert len(out) == 1
    ver, addr, cmd, pl = out[0]
    assert ver == CUR_VER
    assert addr == 0x1234
    assert cmd == 0x2002
    assert len(pl) == 65535
    assert bytes(pl) == payload

    parser = StreamParser(max_len=65535)
    p_small = Proto.pack(0x1003, b"xyz", addr=0xFFFF)
    parser.feed(b"\x00\x01" + p_small)
    out = list(parser.pop())
    assert len(out) == 1
    assert bytes(out[0][3]) == b"xyz"

    print("OK")


if __name__ == "__main__":
    main()

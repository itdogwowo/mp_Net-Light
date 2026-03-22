import os
import sys
import struct


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from tools.net_bench import WSFrameReader


class FakeConn:
    def __init__(self, data: bytes, step=7):
        self._data = memoryview(data)
        self._pos = 0
        self._step = step

    def recv_into(self, buf):
        if self._pos >= len(self._data):
            raise BlockingIOError()
        n = len(buf)
        take = len(self._data) - self._pos
        if take > n:
            take = n
        if take > self._step:
            take = self._step
        buf[:take] = self._data[self._pos : self._pos + take]
        self._pos += take
        return take


def _frame(payload: bytes, masked=False):
    b0 = 0x82
    ln = len(payload)
    hdr = bytearray([b0])
    if ln <= 125:
        hdr.append((0x80 if masked else 0) | ln)
    elif ln <= 65535:
        hdr.append((0x80 if masked else 0) | 126)
        hdr.extend(struct.pack(">H", ln))
    else:
        hdr.append((0x80 if masked else 0) | 127)
        hdr.extend(struct.pack(">Q", ln))
    if not masked:
        return bytes(hdr) + payload
    mask = b"\x01\x02\x03\x04"
    hdr.extend(mask)
    out = bytearray(payload)
    for i in range(ln):
        out[i] ^= mask[i & 3]
    return bytes(hdr) + bytes(out)


def test_unmasked_multi_frames():
    r = WSFrameReader(recv_size=16)
    p1 = b"abc"
    p2 = bytes(range(200))
    raw = _frame(p1) + _frame(p2)
    conn = FakeConn(raw, step=5)
    out = []
    for _ in range(50):
        out.extend(r.recv_payloads(conn))
        if len(out) == 2:
            break
    assert out == [p1, p2]


def test_masked_frame():
    r = WSFrameReader(recv_size=16)
    p = bytes(range(50))
    raw = _frame(p, masked=True)
    conn = FakeConn(raw, step=4)
    out = []
    for _ in range(50):
        out.extend(r.recv_payloads(conn))
        if out:
            break
    assert out == [p]


if __name__ == "__main__":
    test_unmasked_multi_frames()
    test_masked_frame()
    print("ok")


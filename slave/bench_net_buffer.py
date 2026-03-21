import sys
import time
import gc

from lib.proto import Proto, StreamParser

try:
    from lib.buffer_hub import AtomicStreamHub
except Exception:
    class AtomicStreamHub:
        def __init__(self, size, num_buffers=3):
            self._bufs = [bytearray(size) for _ in range(num_buffers)]
            self._views = [memoryview(b) for b in self._bufs]
            self._st = [0] * num_buffers
            self._w = 0
            self._r = 0
            self._last = -1

        def get_write_view(self):
            if self._st[self._w] != 0:
                return None
            return self._views[self._w]

        def commit(self):
            if self._st[self._w] != 0:
                return
            self._st[self._w] = 1
            self._w = (self._w + 1) % len(self._st)

        def get_read_view(self):
            if self._last != -1:
                self._st[self._last] = 0
                self._last = -1
            if self._st[self._r] != 1:
                return None
            self._st[self._r] = 2
            self._last = self._r
            self._r = (self._r + 1) % len(self._st)
            return self._views[self._last]


IS_MICROPYTHON = (sys.implementation.name == "micropython")


def _ticks_us():
    if IS_MICROPYTHON:
        return time.ticks_us()
    return time.perf_counter_ns() // 1000


def _ticks_diff_us(a, b):
    if IS_MICROPYTHON:
        return time.ticks_diff(a, b)
    return a - b


def _mem_free():
    if hasattr(gc, "mem_free"):
        return gc.mem_free()
    return -1


def _mk_packet(payload_len):
    payload = bytearray(payload_len)
    for i in range(payload_len):
        payload[i] = i & 0xFF
    return Proto.pack(0x1003, payload, addr=0x1234)


def _bench_direct(pkt, pkt_count, chunk_size, max_len):
    parser = StreamParser(max_len=max_len)
    rx_buf = bytearray(chunk_size)
    rx_mv = memoryview(rx_buf)

    total_in = 0
    total_pkt = 0

    t0 = _ticks_us()
    for _ in range(pkt_count):
        mv = memoryview(pkt)
        pos = 0
        ln = len(mv)
        while pos < ln:
            take = ln - pos
            if take > chunk_size:
                take = chunk_size
            rx_mv[:take] = mv[pos : pos + take]
            total_in += take
            parser.feed(rx_mv[:take])
            for _ver, _addr, _cmd, _pl in parser.pop():
                total_pkt += 1
            pos += take
    t1 = _ticks_us()

    dt = _ticks_diff_us(t1, t0)
    return dt, total_in, total_pkt


def _bench_hub(pkt, pkt_count, chunk_size, max_len, num_buffers=4):
    parser = StreamParser(max_len=max_len)
    hub = AtomicStreamHub(chunk_size + 3, num_buffers=num_buffers)

    total_in = 0
    total_pkt = 0

    def drain():
        nonlocal total_pkt
        while True:
            r = hub.get_read_view()
            if r is None:
                return
            ln = int(r[1]) | (int(r[2]) << 8)
            if ln:
                parser.feed(r[3 : 3 + ln])
                for _ver, _addr, _cmd, _pl in parser.pop():
                    total_pkt += 1

    t0 = _ticks_us()
    for _ in range(pkt_count):
        mv = memoryview(pkt)
        pos = 0
        ln = len(mv)
        while pos < ln:
            take = ln - pos
            if take > chunk_size:
                take = chunk_size

            while True:
                w = hub.get_write_view()
                if w is not None:
                    break
                drain()

            w[0] = 0
            w[1] = take & 0xFF
            w[2] = (take >> 8) & 0xFF
            w[3 : 3 + take] = mv[pos : pos + take]
            hub.commit()
            total_in += take
            pos += take

            drain()

    drain()
    t1 = _ticks_us()

    dt = _ticks_diff_us(t1, t0)
    return dt, total_in, total_pkt


def _report(name, dt_us, total_in, total_pkt):
    if dt_us <= 0:
        dt_us = 1
    kb = total_in / 1024
    sec = dt_us / 1_000_000
    kb_s = kb / sec
    pps = total_pkt / sec
    print(name)
    print("  bytes:", total_in, "packets:", total_pkt)
    print("  time_us:", dt_us, "kb_s:", int(kb_s), "pps:", int(pps))


def run(payload_len=4096, pkt_count=200, chunk_size=4096, max_len=65535, hub_buffers=4):
    gc.collect()
    print("mem_free:", _mem_free())
    pkt = _mk_packet(payload_len)
    print("packet_len:", len(pkt), "payload_len:", payload_len, "pkt_count:", pkt_count, "chunk:", chunk_size)

    gc.collect()
    t, n, p = _bench_direct(pkt, pkt_count, chunk_size, max_len)
    _report("direct_buffer", t, n, p)

    gc.collect()
    t, n, p = _bench_hub(pkt, pkt_count, chunk_size, max_len, num_buffers=hub_buffers)
    _report("hub_queue", t, n, p)

    print("mem_free:", _mem_free())


if __name__ == "__main__":
    run()

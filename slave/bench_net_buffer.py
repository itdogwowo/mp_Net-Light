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


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0
    mid = n // 2
    if n & 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


def _run_once(pkt, pkt_count, chunk_size, max_len, hub_buffers, gc_off):
    gc.collect()
    if gc_off and hasattr(gc, "disable"):
        gc.disable()
    try:
        t1, n1, p1 = _bench_direct(pkt, pkt_count, chunk_size, max_len)
        t2, n2, p2 = _bench_hub(pkt, pkt_count, chunk_size, max_len, num_buffers=hub_buffers)
    finally:
        if gc_off and hasattr(gc, "enable"):
            gc.enable()
    return (t1, n1, p1), (t2, n2, p2)


def run(payload_len=4096, pkt_count=200, chunk_size=4096, max_len=65535, hub_buffers=4, repeat=1, warmup=0, gc_off=False):
    gc.collect()
    print("mem_free:", _mem_free())
    pkt = _mk_packet(payload_len)
    print(
        "packet_len:",
        len(pkt),
        "payload_len:",
        payload_len,
        "pkt_count:",
        pkt_count,
        "chunk:",
        chunk_size,
        "repeat:",
        repeat,
        "warmup:",
        warmup,
        "gc_off:",
        1 if gc_off else 0,
    )

    for _ in range(warmup):
        _run_once(pkt, pkt_count, chunk_size, max_len, hub_buffers, gc_off)

    direct_times = []
    hub_times = []
    last_direct = None
    last_hub = None
    for _ in range(repeat):
        direct, hub = _run_once(pkt, pkt_count, chunk_size, max_len, hub_buffers, gc_off)
        last_direct = direct
        last_hub = hub
        direct_times.append(direct[0])
        hub_times.append(hub[0])

    if last_direct:
        _report("direct_buffer", last_direct[0], last_direct[1], last_direct[2])
    if last_hub:
        _report("hub_queue", last_hub[0], last_hub[1], last_hub[2])

    if repeat > 1:
        print("direct_time_us_median:", _median(direct_times), "min:", min(direct_times), "max:", max(direct_times))
        print("hub_time_us_median:", _median(hub_times), "min:", min(hub_times), "max:", max(hub_times))

    print("mem_free:", _mem_free())


def run_large(payload_len=65535, chunk_size=4096, pkt_count=10, repeat=5, warmup=1, gc_off=True, hub_buffers=4):
    run(
        payload_len=payload_len,
        pkt_count=pkt_count,
        chunk_size=chunk_size,
        max_len=65535,
        hub_buffers=hub_buffers,
        repeat=repeat,
        warmup=warmup,
        gc_off=gc_off,
    )


if __name__ == "__main__":
    run()

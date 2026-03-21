import sys
import time
import gc

from lib.proto import Proto, StreamParser
import bench_net_buffer as single

try:
    from lib.buffer_hub import AtomicStreamHub
except Exception:
    AtomicStreamHub = single.AtomicStreamHub

try:
    import _thread
except Exception:
    _thread = None


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


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0
    mid = n // 2
    if n & 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


def bench_hub_dual(pkt, pkt_count, chunk_size, max_len=65535, hub_buffers=4, gc_off=True):
    if _thread is None:
        return None

    hub = AtomicStreamHub(chunk_size + 3, num_buffers=hub_buffers)
    state = {"want": pkt_count, "got": 0, "done": 0}
    parser = StreamParser(max_len=max_len)

    def consumer():
        while True:
            r = hub.get_read_view()
            if r is None:
                if state["done"] and state["got"] >= state["want"]:
                    return
                time.sleep_ms(0)
                continue
            ln = int(r[1]) | (int(r[2]) << 8)
            if ln:
                parser.feed(r[3 : 3 + ln])
                for _ver, _addr, _cmd, _pl in parser.pop():
                    state["got"] += 1

    gc.collect()
    if gc_off and hasattr(gc, "disable"):
        gc.disable()
    try:
        _thread.start_new_thread(consumer, ())
        t0 = _ticks_us()

        mv = memoryview(pkt)
        for _ in range(pkt_count):
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
                    time.sleep_ms(0)
                w[0] = 0
                w[1] = take & 0xFF
                w[2] = (take >> 8) & 0xFF
                w[3 : 3 + take] = mv[pos : pos + take]
                hub.commit()
                pos += take

        state["done"] = 1
        while state["got"] < state["want"]:
            time.sleep_ms(0)
        t1 = _ticks_us()
    finally:
        if gc_off and hasattr(gc, "enable"):
            gc.enable()

    total_in = len(pkt) * pkt_count
    dt = _ticks_diff_us(t1, t0)
    return dt, total_in, state["got"]


def run_matrix(payload_lens=None, chunk_sizes=None, pkt_count=200, repeat=5, warmup=1, gc_off=True, hub_buffers=4, dual=False):
    if payload_lens is None:
        payload_lens = [256, 1024, 4096, 16384, 32768, 65535]
        payload_lens = [16384, 32768, 65535]
    if chunk_sizes is None:
        chunk_sizes = [4096, 16384]

    print("mem_free:", _mem_free(), "dual:", 1 if dual else 0)
    for payload_len in payload_lens:
        for chunk in chunk_sizes:
            if chunk < 64:
                continue

            times = []
            for i in range(warmup + repeat):
                pkt = _mk_packet(payload_len)
                if dual:
                    res = bench_hub_dual(pkt, pkt_count, chunk, max_len=65535, hub_buffers=hub_buffers, gc_off=gc_off)
                    if res is None:
                        print("dual_core_not_supported")
                        return
                    t, n, p = res
                else:
                    gc.collect()
                    if gc_off and hasattr(gc, "disable"):
                        gc.disable()
                    try:
                        t, n, p = single._bench_direct(pkt, pkt_count, chunk, 65535)
                    finally:
                        if gc_off and hasattr(gc, "enable"):
                            gc.enable()
                if i >= warmup:
                    times.append(t)

            med = _median(times)
            if med <= 0:
                med = 1
            kb_s = int((n / 1024) / (med / 1_000_000))
            print("payload:", payload_len, "chunk:", chunk, "kb_s:", kb_s, "time_us_med:", med)


if __name__ == "__main__":
    run_matrix(dual=0)

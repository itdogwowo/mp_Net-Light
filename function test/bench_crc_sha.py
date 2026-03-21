import sys
import time
import gc

from lib.proto import Proto

try:
    import hashlib
except Exception:
    try:
        import uhashlib as hashlib
    except Exception:
        hashlib = None

try:
    import ubinascii as binascii
except Exception:
    try:
        import binascii
    except Exception:
        binascii = None


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


def _fill(buf):
    mv = memoryview(buf)
    for i in range(len(mv)):
        mv[i] = i & 0xFF


def _bench_crc(buf, loops):
    return None, None


def _bench_sha256(buf, loops):
    if hashlib is None:
        return None, None
    t0 = _ticks_us()
    x = 0
    mv = memoryview(buf)
    for _ in range(loops):
        h = hashlib.sha256()
        h.update(mv)
        d = h.digest()
        x ^= d[0]
    t1 = _ticks_us()
    return _ticks_diff_us(t1, t0), x


def _bench_crc32(buf, loops):
    if binascii is None or not hasattr(binascii, "crc32"):
        return None, None
    t0 = _ticks_us()
    x = 0
    mv = memoryview(buf)
    for _ in range(loops):
        x ^= binascii.crc32(mv)
    t1 = _ticks_us()
    return _ticks_diff_us(t1, t0), x


def _report(name, dt_us, total_bytes):
    if dt_us is None:
        print(name, "not_available")
        return
    if dt_us <= 0:
        dt_us = 1
    sec = dt_us / 1_000_000
    mb_s = (total_bytes / (1024 * 1024)) / sec
    print(name, "time_us:", dt_us, "mb_s:", "{:.2f}".format(mb_s))


def run(size=65535, loops=200, warmup=10, gc_off=True):
    buf = bytearray(size)
    _fill(buf)

    gc.collect()
    print("mem_free:", _mem_free(), "size:", size, "loops:", loops, "warmup:", warmup, "gc_off:", 1 if gc_off else 0)

    if gc_off and hasattr(gc, "disable"):
        gc.disable()

    try:
        for _ in range(warmup):
            if hashlib is not None:
                _bench_sha256(buf, 1)

        dt, _x = _bench_sha256(buf, loops)
        _report("sha256", dt, size * loops)

        dt, _x = _bench_crc32(buf, loops)
        _report("crc32", dt, size * loops)
    finally:
        if gc_off and hasattr(gc, "enable"):
            gc.enable()


def run_crc_compare(size=65535, loops=500, warmup=20, gc_off=True):
    run(size=size, loops=loops, warmup=warmup, gc_off=gc_off)


if __name__ == "__main__":
    run()

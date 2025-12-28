# /lib/state.py
import time

def now_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)

STATE = {
    "boot_ms": now_ms(),
    "file": {"last_ok": None, "last_error": None, "last_path": None},
}
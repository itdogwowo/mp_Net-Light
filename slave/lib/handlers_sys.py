# /lib/handlers_sys.py
import os
import gc
import sys
import ubinascii
from state import STATE, now_ms

def get_machine_info():
    import machine
    info = {}

    # version / port / mcu model
    info["mpy_ver"] = sys.version
    try:
        info["uname"] = str(os.uname())
    except Exception:
        info["uname"] = "N/A"

    # unique id
    try:
        uid = machine.unique_id()
        info["uid_hex"] = ubinascii.hexlify(uid).decode()
    except Exception:
        info["uid_hex"] = "N/A"

    # flash size & free (varies by port)
    try:
        st = os.statvfs("/")
        # statvfs: f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, ...
        bsize = st[0]
        blocks = st[2]
        bfree = st[3]
        info["fs_total"] = bsize * blocks
        info["fs_free"] = bsize * bfree
    except Exception:
        info["fs_total"] = None
        info["fs_free"] = None

    # memory
    try:
        gc.collect()
        info["mem_free"] = gc.mem_free()
        info["mem_alloc"] = gc.mem_alloc()
    except Exception:
        info["mem_free"] = None
        info["mem_alloc"] = None

    info["uptime_ms"] = now_ms() - STATE["boot_ms"]
    return info
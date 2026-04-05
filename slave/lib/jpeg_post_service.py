import time

from lib.buffer_hub import AtomicStreamHub
from lib.jpeg_service import HDR_OUT, OUT_STRUCT


def ensure_jpeg_post_service(bus, name="jpeg_post"):
    svc = bus.get_service(name)
    if svc is not None:
        return svc
    svc = {
        "api": 1,
        "enable": True,
        "hook": None,
        "hook_enable": False,
        "cfg_epoch": 0,
        "output": [],
        "_idx_output": {},
        "state": [],
        "_idx_state": {},
        "last_err": "",
        "last_ms": 0,
    }
    bus.register_service(name, svc)
    if name == "jpeg_post":
        try:
            bus.register_provider(
                "jpeg_post_frames",
                lambda: sum(int(st.get("frames", 0) or 0) for st in (svc.get("state") or [])),
            )
            bus.register_provider(
                "jpeg_post_last_ms",
                lambda: max([int(st.get("last_ms", 0) or 0) for st in (svc.get("state") or [])] or [0]),
            )
        except Exception:
            pass
    return svc


def _set_error(svc, err):
    try:
        svc["last_err"] = str(err)
        svc["last_ms"] = time.ticks_ms()
    except Exception:
        pass


def set_hook(bus, fn=None, *, enable=True, name="jpeg_post"):
    svc = ensure_jpeg_post_service(bus, name=name)
    svc["hook"] = fn
    svc["hook_enable"] = bool(enable and fn is not None)
    svc["cfg_epoch"] = (int(svc.get("cfg_epoch", 0) or 0) + 1) & 0xFFFF
    return svc


def configure_from_jpeg_service(bus, jpeg_svc, *, name="jpeg_post"):
    svc = ensure_jpeg_post_service(bus, name=name)
    outs = jpeg_svc.get("output") or []

    output = []
    state = []
    for it in outs:
        try:
            label = str(it.get("label") or "")
            if not label:
                continue
            if not it.get("enabled", True):
                continue
            rect = it.get("rect") or {}
            x = int(rect.get("x", 0) or 0)
            y = int(rect.get("y", 0) or 0)
            w = int(rect.get("w", 0) or 0)
            h = int(rect.get("h", 0) or 0)
            meta = it.get("meta") or {}
            bpp = int(meta.get("bpp", 2) or 2)
            if w <= 0 or h <= 0 or bpp <= 0:
                continue
            frame_bytes = w * h * bpp
            out_hub = AtomicStreamHub(HDR_OUT + frame_bytes, num_buffers=3)
            output.append(
                {
                    "label": label,
                    "enabled": True,
                    "rect": {"x": x, "y": y, "w": w, "h": h},
                    "bpp": bpp,
                    "frame_bytes": frame_bytes,
                    "hub": out_hub,
                }
            )
            state.append(
                {
                    "label": label,
                    "frames": 0,
                    "last_seq": 0,
                    "last_ms": 0,
                    "last_err": "",
                }
            )
        except Exception as e:
            _set_error(svc, e)

    svc["output"] = output
    svc["_idx_output"] = {it["label"]: i for i, it in enumerate(output)}
    svc["state"] = state
    svc["_idx_state"] = {it["label"]: i for i, it in enumerate(state)}
    svc["cfg_epoch"] = (int(svc.get("cfg_epoch", 0) or 0) + 1) & 0xFFFF
    return svc


def get_output_entry(svc, label):
    i = (svc.get("_idx_output") or {}).get(label, None)
    if i is None:
        return None
    out = svc.get("output") or []
    if i < 0 or i >= len(out):
        return None
    return out[i]


def get_state_entry(svc, label):
    i = (svc.get("_idx_state") or {}).get(label, None)
    if i is None:
        return None
    st = svc.get("state") or []
    if i < 0 or i >= len(st):
        return None
    return st[i]


def pack_full_frame(buf, payload_len, *, seq=0, x=0, y=0, w=0, h=0, fmt_code=0):
    OUT_STRUCT.pack_into(buf, 0, int(payload_len), int(seq), int(x), int(y), int(w), int(h), 3, int(fmt_code))

import time


def ensure_display_service(bus, name="display"):
    svc = bus.get_service(name)
    if svc is not None:
        return svc

    svc = {
        "api": 1,
        "enable": True,
        "cfg_epoch": 0,
        "last_err": "",
        "last_ms": 0,
        "displayed_blocks": 0,
        "rr": 0,
        "hook_enable": False,
        "hook": None,
        "full_frame_only": False,
    }
    bus.register_service(name, svc)
    try:
        bus.register_provider("display_blocks", lambda: int(svc.get("displayed_blocks", 0) or 0))
    except Exception:
        pass
    return svc


def service_error(svc, err):
    try:
        svc["last_err"] = str(err)
        svc["last_ms"] = time.ticks_ms()
    except Exception:
        pass


def set_frame_hook(bus, fn=None, *, enable=True, full_frame_only=True, name="display"):
    svc = ensure_display_service(bus, name=name)
    svc["hook"] = fn
    svc["hook_enable"] = bool(enable and fn is not None)
    svc["full_frame_only"] = bool(full_frame_only)
    svc["cfg_epoch"] = (int(svc.get("cfg_epoch", 0) or 0) + 1) & 0xFFFF
    return svc

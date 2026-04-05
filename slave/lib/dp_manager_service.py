try:
    import ujson as json
except Exception:
    import json

try:
    import ustruct as _struct
except Exception:
    import struct as _struct

from lib.buffer_hub import AtomicStreamHub


HDR_IN = 24
IN_STRUCT = _struct.Struct("<IHHhhHHHHI")


def ensure_dp_manager_service(bus, name="dp_manager"):
    svc = bus.get_service(name)
    if svc is not None:
        return svc

    svc = {
        "api": 1,
        "enable": True,
        "dp_config_path": "/dp_config.json",
        "assets_root": "",
        "frame_format": "{frame:03d}.jpeg",
        "jpeg": {"pixel_format": "RGB565_LE", "rotation": 0, "block": True, "step_blocks": 1, "max_jpeg_bytes": 49152},
        "layout": [],
        "schedule": [],
        "sch_i": 0,
        "seq": 1,
        "cfg_epoch": 0,
        "jpeg_in": None,
        "inflight": 0,
        "last_err": "",
        "last_ms": 0,
        "last_loaded": None,
    }
    bus.register_service(name, svc)
    return svc


def _dir_name(path):
    if not path:
        return ""
    path = str(path)
    i = path.rfind("/")
    if i < 0:
        return ""
    return path[:i]


def _norm_path(p):
    if not p:
        return ""
    p = str(p)
    if p.endswith("/"):
        return p[:-1]
    return p


def _extract_layout(dp):
    layout = dp.get("display_Layout") or dp.get("layout") or []
    if not isinstance(layout, list):
        return []
    return layout


def _label_of_item(item):
    if not isinstance(item, dict):
        return ""
    return str(item.get("label") or item.get("type") or "")


def _rect_of_item(item):
    if not isinstance(item, dict):
        return 0, 0, 0, 0, 1
    x = int(item.get("x", 0) or 0)
    y = int(item.get("y", 0) or 0)
    w = int(item.get("width", item.get("w", item.get("W", 0) or 0)) or 0)
    h = int(item.get("height", item.get("h", item.get("H", 0) or 0)) or 0)
    depth = int(item.get("depth", 1) or 1)
    if depth <= 0:
        depth = 1
    return x, y, w, h, depth


def _bpp(pixel_format):
    pf = str(pixel_format or "")
    if pf.startswith("RGB565") or pf == "CbYCrY":
        return 2
    if pf == "RGB888":
        return 3
    return 2


def load_dp_config(path):
    with open(path, "r") as f:
        return json.loads(f.read())


def configure_from_dp_config(bus, dp, *, dp_config_path=None, service_name="dp_manager"):
    svc = ensure_dp_manager_service(bus, name=service_name)

    dp = dp if isinstance(dp, dict) else {}
    dp_jpeg = dp.get("jpeg") if isinstance(dp.get("jpeg"), dict) else {}

    assets_root = dp.get("assets_root") or dp.get("root_path") or ""
    if not assets_root and dp_config_path:
        assets_root = _dir_name(dp_config_path)
    assets_root = _norm_path(assets_root)

    frame_format = dp.get("frame_format") or dp.get("jpeg_frame_format") or svc.get("frame_format") or "{frame:03d}.jpeg"

    jpeg_cfg = dict(svc.get("jpeg") or {})
    for k in ("pixel_format", "rotation", "block", "step_blocks", "max_jpeg_bytes"):
        if k in dp_jpeg:
            jpeg_cfg[k] = dp_jpeg.get(k)

    pixel_format = jpeg_cfg.get("pixel_format") or "RGB565_LE"
    bpp = _bpp(pixel_format)

    layout = _extract_layout(dp)
    items = []
    for it in layout:
        label = _label_of_item(it)
        if not label:
            continue
        x, y, w, h, depth = _rect_of_item(it)
        if int(w) <= 0 or int(h) <= 0:
            continue
        items.append({"label": label, "x": int(x), "y": int(y), "w": int(w), "h": int(h), "depth": int(depth), "bpp": int(bpp)})

    schedule = []
    for label_i, it in enumerate(items):
        depth = int(it.get("depth", 1) or 1)
        for fi in range(depth):
            schedule.append(
                {
                    "label": it["label"],
                    "label_id": int(label_i),
                    "frame": int(fi),
                    "x": int(it["x"]),
                    "y": int(it["y"]),
                    "w": int(it["w"]),
                    "h": int(it["h"]),
                    "bpp": int(it["bpp"]),
                }
            )

    max_jpeg_bytes = int(jpeg_cfg.get("max_jpeg_bytes", 0) or 0)
    if max_jpeg_bytes <= 0:
        max_jpeg_bytes = 49152

    jpeg_in = AtomicStreamHub(HDR_IN + max_jpeg_bytes, num_buffers=3)

    svc["dp_config_path"] = str(dp_config_path or svc.get("dp_config_path") or "/dp_config.json")
    svc["assets_root"] = assets_root
    svc["frame_format"] = str(frame_format)
    svc["jpeg"] = jpeg_cfg
    svc["layout"] = items
    svc["schedule"] = schedule
    svc["sch_i"] = 0
    svc["jpeg_in"] = jpeg_in
    svc["inflight"] = 0
    svc["last_err"] = ""
    svc["cfg_epoch"] = (int(svc.get("cfg_epoch", 0) or 0) + 1) & 0xFFFF
    return svc


def pack_in_header(buf, payload_len, *, seq=0, label_id=0, x=0, y=0, w=0, h=0, bpp=2, flags=0, path_hash=0):
    IN_STRUCT.pack_into(buf, 0, int(payload_len), int(seq), int(label_id), int(x), int(y), int(w), int(h), int(bpp), int(flags), int(path_hash))


def unpack_in_header(buf):
    return IN_STRUCT.unpack_from(buf, 0)

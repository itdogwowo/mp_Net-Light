try:
    import ujson as json
except Exception:
    import json

try:
    import ustruct as _struct
except Exception:
    import struct as _struct

from lib.buffer_hub import AtomicStreamHub


HDR_IN = 16
HDR_OUT = 16

class _MiniStruct:
    def __init__(self, fmt):
        self.fmt = fmt
        self.size = _struct.calcsize(fmt)

    def pack_into(self, buf, offset, *args):
        return _struct.pack_into(self.fmt, buf, offset, *args)

    def unpack_from(self, buf, offset=0):
        return _struct.unpack_from(self.fmt, buf, offset)

IN_STRUCT = _MiniStruct("<HHhhHHI")
OUT_STRUCT = _MiniStruct("<HHhhHHHH")


def ensure_jpeg_service(bus, name="jpeg_decoder"):
    svc = bus.get_service(name)
    if svc is not None:
        return svc

    svc = {
        "api": 1,
        "enable": False,
        "decoder": None,
        "pixel_format": "RGB565_LE",
        "rotation": 0,
        "block": True,
        "return_bytes": False,
        "step_blocks": 0,
        "max_jpeg_bytes": 0,
        "cfg_epoch": 0,
        "source": [],
        "output": [],
        "state": [],
        "_idx_source": {},
        "_idx_output": {},
        "_idx_state": {},
        "_rr": 0,
    }
    bus.register_service(name, svc)
    if name == "jpeg_decoder":
        try:
            bus.register_service("jepg_decoder", svc)
        except Exception:
            pass
    return svc


def load_dp_config(path):
    with open(path, "r") as f:
        return json.loads(f.read())


def _bpp_for_pixel_format(pixel_format):
    pf = str(pixel_format or "")
    if pf.startswith("RGB565") or pf == "CbYCrY":
        return 2
    if pf == "RGB888":
        return 3
    return 2


def _norm_path(p):
    if not p:
        return ""
    p = str(p)
    if p.endswith("/"):
        return p[:-1]
    return p


def _dir_name(path):
    if not path:
        return ""
    path = str(path)
    i = path.rfind("/")
    if i < 0:
        return ""
    return path[:i]


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
        return 0, 0, 0, 0
    x = int(item.get("x", 0) or 0)
    y = int(item.get("y", 0) or 0)
    w = int(item.get("width", 0) or 0)
    h = int(item.get("height", 0) or 0)
    return x, y, w, h


def _manifest_max_under(manifest, base_dir):
    if not manifest:
        return 0
    base_dir = _norm_path(base_dir)
    best = 0
    for p, meta in manifest.items():
        try:
            if base_dir and not str(p).startswith(base_dir + "/"):
                continue
            s = meta.get("s", 0) if isinstance(meta, dict) else 0
            s = int(s or 0)
            if s > best:
                best = s
        except Exception:
            pass
    return best


def configure_from_dp_config(bus, dp, dp_config_path=None, manifest=None, service_name="jpeg_decoder"):
    svc = ensure_jpeg_service(bus, name=service_name)

    jpeg_cfg = dp.get("jpeg") if isinstance(dp, dict) else None
    if not isinstance(jpeg_cfg, dict):
        jpeg_cfg = {}

    pixel_format = jpeg_cfg.get("pixel_format") or svc.get("pixel_format") or "RGB565_LE"
    rotation = int(jpeg_cfg.get("rotation", svc.get("rotation", 0) or 0) or 0)
    block = bool(jpeg_cfg.get("block", svc.get("block", True)))
    return_bytes = bool(jpeg_cfg.get("return_bytes", svc.get("return_bytes", False)))
    step_blocks = int(jpeg_cfg.get("step_blocks", svc.get("step_blocks", 0) or 0) or 0)

    layout = _extract_layout(dp if isinstance(dp, dict) else {})
    labels = []
    rects = {}
    for it in layout:
        label = _label_of_item(it)
        if not label:
            continue
        if label not in rects:
            rects[label] = _rect_of_item(it)
            labels.append(label)

    base_dir = ""
    if isinstance(dp, dict):
        base_dir = dp.get("assets_root") or dp.get("root_path") or ""
    if not base_dir and dp_config_path:
        base_dir = _dir_name(dp_config_path)
    base_dir = _norm_path(base_dir)

    max_jpeg_bytes = int(jpeg_cfg.get("max_jpeg_bytes", 0) or 0)
    if max_jpeg_bytes <= 0:
        max_jpeg_bytes = _manifest_max_under(manifest, base_dir)
    if max_jpeg_bytes <= 0:
        max_jpeg_bytes = 49152

    bpp = _bpp_for_pixel_format(pixel_format)
    max_block_h = int(jpeg_cfg.get("max_block_h", 16) or 16)
    if max_block_h <= 0:
        max_block_h = 16

    source = []
    output = []
    state = []

    for label in labels:
        x, y, w, h = rects.get(label, (0, 0, 0, 0))
        if w <= 0 or h <= 0:
            continue

        src_hub = AtomicStreamHub(HDR_IN + max_jpeg_bytes, num_buffers=3)
        max_frame_bytes = w * h * bpp
        max_block_bytes = w * max_block_h * bpp
        out_block_hub = AtomicStreamHub(HDR_OUT + max_block_bytes, num_buffers=3)
        framebuf = bytearray(max_frame_bytes)

        source.append(
            {
                "label": label,
                "hub": src_hub,
                "enabled": True,
                "route_to": label,
            }
        )
        output.append(
            {
                "label": label,
                "enabled": True,
                "mode": "framebuf",
                "rect": {"x": x, "y": y, "w": w, "h": h},
                "framebuf": framebuf,
                "block_hub": out_block_hub,
                "meta": {"w": 0, "h": 0, "bpp": bpp, "fmt": pixel_format, "seq": 0, "x0": 0, "y0": 0},
            }
        )
        state.append(
            {
                "label": label,
                "busy": 0,
                "decoded_frames": 0,
                "decoded_blocks": 0,
                "skipped": 0,
                "last_err": "",
                "last_ms": 0,
                "last_path_hash": 0,
            }
        )

    svc["decoder"] = None
    svc["pixel_format"] = pixel_format
    svc["rotation"] = rotation
    svc["block"] = block
    svc["return_bytes"] = return_bytes
    svc["step_blocks"] = step_blocks
    svc["max_jpeg_bytes"] = max_jpeg_bytes
    svc["source"] = source
    svc["output"] = output
    svc["state"] = state

    svc["_idx_source"] = {it["label"]: i for i, it in enumerate(source)}
    svc["_idx_output"] = {it["label"]: i for i, it in enumerate(output)}
    svc["_idx_state"] = {it["label"]: i for i, it in enumerate(state)}
    svc["_rr"] = 0
    svc["cfg_epoch"] = (int(svc.get("cfg_epoch", 0) or 0) + 1) & 0xFFFF
    svc["enable"] = True

    return svc


def get_source_entry(svc, label):
    i = (svc.get("_idx_source") or {}).get(label, None)
    if i is None:
        return None
    src = svc.get("source") or []
    if i < 0 or i >= len(src):
        return None
    return src[i]


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


def pack_in_header(buf, payload_len, *, seq=0, x0=0, y0=0, flags=0, fmt_code=0, path_hash=0):
    IN_STRUCT.pack_into(buf, 0, int(payload_len), int(seq), int(x0), int(y0), int(flags), int(fmt_code), int(path_hash))


def unpack_in_header(buf):
    return IN_STRUCT.unpack_from(buf, 0)


def pack_block_header(buf, payload_len, *, seq=0, x=0, y=0, w=0, h=0, flags=0, fmt_code=0):
    OUT_STRUCT.pack_into(buf, 0, int(payload_len), int(seq), int(x), int(y), int(w), int(h), int(flags), int(fmt_code))


def unpack_block_header(buf):
    return OUT_STRUCT.unpack_from(buf, 0)

import ustruct

from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub


_IN_HEADER_SIZE = 12
_OUT_HEADER_SIZE = 16

_FMT_RGB565_BE = 0
_FMT_RGB565_LE = 1
_FMT_RGB888 = 2


def _fmt_code(pixel_format):
    if pixel_format == "RGB565_LE":
        return _FMT_RGB565_LE
    if pixel_format == "RGB888":
        return _FMT_RGB888
    return _FMT_RGB565_BE


def _dir_name(path):
    if not path:
        return ""
    path = str(path)
    i = path.rfind("/")
    if i < 0:
        return ""
    return path[:i]


def _join(a, b):
    if not a:
        return str(b)
    if not b:
        return str(a)
    a = str(a)
    b = str(b)
    if a.endswith("/"):
        return a + b.lstrip("/")
    return a + "/" + b.lstrip("/")


class JpegPipe:
    def __init__(
        self,
        max_jpeg_bytes,
        max_width,
        max_block_h=16,
        bytes_per_pixel=2,
        in_buffers=2,
        out_buffers=4,
        pixel_format="RGB565_BE",
        x=0,
        y=0,
    ):
        self.max_jpeg_bytes = int(max_jpeg_bytes)
        self.max_width = int(max_width)
        self.max_block_h = int(max_block_h)
        self.bytes_per_pixel = int(bytes_per_pixel)
        self.in_buffers = int(in_buffers)
        self.out_buffers = int(out_buffers)
        self.pixel_format = pixel_format
        self.x = int(x)
        self.y = int(y)

        self.jpeg_in = AtomicStreamHub(_IN_HEADER_SIZE + self.max_jpeg_bytes, num_buffers=self.in_buffers)
        self.jpeg_blocks = AtomicStreamHub(
            _OUT_HEADER_SIZE + (self.max_width * self.max_block_h * self.bytes_per_pixel),
            num_buffers=self.out_buffers,
        )

        self._seq = 0

    def next_seq(self):
        self._seq = (self._seq + 1) & 0xFFFF
        return self._seq

    def fmt_code(self):
        return _fmt_code(self.pixel_format)

    def pack_in_header(self, mv, n, x=0, y=0, flags=0):
        ustruct.pack_into("<IHHI", mv, 0, int(n), int(x), int(y), int(flags))

    def unpack_in_header(self, mv):
        return ustruct.unpack_from("<IHHI", mv, 0)

    def pack_block_header(self, mv, payload_len, x, y, w, h, flags, fmt):
        ustruct.pack_into("<IHHHHHH", mv, 0, int(payload_len), int(x), int(y), int(w), int(h), int(flags), int(fmt))

    def unpack_block_header(self, mv):
        return ustruct.unpack_from("<IHHHHHH", mv, 0)


def ensure_jpeg_pipe(ctx=None):
    pipe = bus.get_service("jpeg_pipe")
    if pipe is not None:
        return pipe

    cfg = bus.shared.get("JPEG") or {}
    dp_config_path = cfg.get("dp_config_path")

    max_width = 320
    max_height = 240
    max_file_bytes = 0
    if dp_config_path:
        try:
            import json

            with open(dp_config_path, "r") as f:
                dp_cfg = json.load(f)
            layout = dp_cfg.get("display_Layout") or dp_cfg.get("layout") or []
            for item in layout:
                w = int(item.get("width", 0) or 0)
                h = int(item.get("height", 0) or 0)
                if w > max_width:
                    max_width = w
                if h > max_height:
                    max_height = h

            base_dir = dp_cfg.get("assets_root") or dp_cfg.get("root_path") or _dir_name(dp_config_path)
            frame_fmt = dp_cfg.get("frame_format") or "{frame:03d}.jpeg"
            try:
                import os

                for item in layout:
                    res = item.get("label") or item.get("type") or ""
                    if not res:
                        continue
                    depth = int(item.get("depth", 1) or 1)
                    if depth <= 0:
                        depth = 1
                    if depth > 512:
                        depth = 512
                    for i in range(depth):
                        name = frame_fmt.format(frame=i, i=i, index=i)
                        p = _join(_join(base_dir, res), name)
                        try:
                            st = os.stat(p)
                            sz = int(st[6])
                            if sz > max_file_bytes:
                                max_file_bytes = sz
                        except Exception:
                            pass
            except Exception:
                pass
            bus.shared["dp_config"] = dp_cfg
        except Exception as e:
            bus.shared.setdefault("task_errors", {})["dp_config"] = str(e)

    bytes_per_pixel = 2
    max_block_h = 16
    if max_file_bytes > 0:
        max_jpeg_bytes = max_file_bytes + 1024
    else:
        max_jpeg_bytes = min(max_width * max_height * 4, 96 * 1024)
    in_buffers = 2
    out_buffers = 4
    pixel_format = "RGB565_BE"
    x = 0
    y = 0

    pipe = JpegPipe(
        max_jpeg_bytes=max_jpeg_bytes,
        max_width=max_width,
        max_block_h=max_block_h,
        bytes_per_pixel=bytes_per_pixel,
        in_buffers=in_buffers,
        out_buffers=out_buffers,
        pixel_format=pixel_format,
        x=x,
        y=y,
    )

    bus.register_service("jpeg_pipe", pipe)
    bus.register_service("jpeg_in", pipe.jpeg_in)
    bus.register_service("jpeg_blocks", pipe.jpeg_blocks)
    bus.shared.setdefault("jpeg_stats", {})
    bus.shared.setdefault("jpeg_state", {"in_seq": 0, "out_seq": 0, "w": 0, "h": 0, "block_h": 0})
    return pipe

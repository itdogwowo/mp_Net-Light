import time

from lib.task import Task
from lib.sys_bus import bus
from lib.jpeg_pipe import ensure_jpeg_pipe


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


class JpegPlayerTask(Task):
    def on_start(self):
        super().on_start()
        self._pipe = ensure_jpeg_pipe(self.ctx)
        self._hub = self._pipe.jpeg_in

        cfg = bus.shared.get("JPEG") or {}
        self._dp_path = cfg.get("dp_config_path")
        self._dp = bus.shared.get("dp_config") or {}
        self._layout = self._dp.get("display_Layout") or self._dp.get("layout") or []
        try:
            self._layout = sorted(self._layout, key=lambda it: int(it.get("level", 0) or 0))
        except Exception:
            pass
        self._frame_fmt = self._dp.get("frame_format") or "{frame:03d}.jpeg"
        self._base_dir = self._dp.get("assets_root") or self._dp.get("root_path") or _dir_name(self._dp_path)

        self._layer_i = 0
        self._frame_i = 0

        self._wait_decode = False
        self._last_decode_ms = (bus.shared.get("jpeg_stats") or {}).get("last_ms", None)
        self._wait_start_ms = time.ticks_ms()
        self._wait_timeout_ms = int(self._dp.get("decode_timeout_ms", 500) or 500)

        bus.shared.setdefault("jpeg_player_enable", True)
        bus.shared.setdefault("jpeg_player_reset", False)

    def _next_item(self):
        if not self._layout:
            return None

        if self._layer_i >= len(self._layout):
            self._layer_i = 0
            self._frame_i = 0

        item = self._layout[self._layer_i]
        depth = int(item.get("depth", 1) or 1)
        if depth <= 0:
            depth = 1

        if self._frame_i >= depth:
            self._layer_i += 1
            self._frame_i = 0
            return self._next_item()

        t = item.get("label") or item.get("type") or ""
        x = int(item.get("x", 0) or 0)
        y = int(item.get("y", 0) or 0)
        f = self._frame_i

        self._frame_i += 1
        return t, f, x, y

    def _resolve_file(self, res_type, frame_idx):
        name = self._frame_fmt.format(frame=frame_idx, i=frame_idx, index=frame_idx)
        return _join(_join(self._base_dir, res_type), name)

    def loop(self):
        if not bus.shared.get("jpeg_enable", True):
            return
        if not bus.shared.get("jpeg_player_enable", True):
            return
        if not self._layout:
            return

        if bus.shared.get("jpeg_player_reset"):
            self._layer_i = 0
            self._frame_i = 0
            bus.shared["jpeg_player_reset"] = False
            self._wait_decode = False

        if self._wait_decode:
            stats = bus.shared.get("jpeg_stats") or {}
            ms = stats.get("last_ms", None)
            if ms == self._last_decode_ms:
                now = time.ticks_ms()
                if time.ticks_diff(now, self._wait_start_ms) > self._wait_timeout_ms:
                    bus.shared.setdefault("task_errors", {})["jpeg_player"] = "decode timeout"
                    self._wait_decode = False
                return
            self._last_decode_ms = ms
            self._wait_decode = False

        item = self._next_item()
        if item is None:
            return

        res_type, frame_idx, x, y = item
        path = self._resolve_file(res_type, frame_idx)

        wv = self._hub.get_write_view()
        if wv is None:
            return

        try:
            with open(path, "rb") as f:
                n = f.readinto(wv[12:])
                if n is None:
                    n = 0
                try:
                    extra = f.read(1)
                    if extra:
                        bus.shared.setdefault("task_errors", {})["jpeg_player"] = "jpeg too large for input buffer"
                except Exception:
                    pass
        except Exception as e:
            bus.shared.setdefault("task_errors", {})["jpeg_player"] = str(e)
            return

        self._pipe.pack_in_header(wv, n, x, y, 0)
        self._hub.commit()
        self._wait_decode = True
        self._wait_start_ms = time.ticks_ms()

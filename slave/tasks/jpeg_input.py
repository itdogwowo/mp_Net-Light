import time

from lib.task import Task
from lib.sys_bus import bus
from lib.jpeg_pipe import ensure_jpeg_pipe


class JpegInputTask(Task):
    def on_start(self):
        super().on_start()
        self._pipe = ensure_jpeg_pipe(self.ctx)
        self._hub = self._pipe.jpeg_in
        self._last_path = None
        self._last_mtime = None
        self._last_push_ms = 0
        self._cooldown_ms = int((bus.shared.get("JPEG") or {}).get("input_cooldown_ms", 0) or 0)
        bus.shared.setdefault("jpeg_path", bus.shared.get("jpeg_path"))

    def _should_push(self, path):
        now = time.ticks_ms()
        if self._cooldown_ms and time.ticks_diff(now, self._last_push_ms) < self._cooldown_ms:
            return False
        if bus.shared.get("jpeg_force_reload"):
            return True
        if path != self._last_path:
            return True
        try:
            import os

            st = os.stat(path)
            mtime = st[8] if len(st) > 8 else None
            if mtime is not None and mtime != self._last_mtime:
                return True
        except Exception:
            return True
        return False

    def _update_file_state(self, path):
        self._last_path = path
        self._last_mtime = None
        try:
            import os

            st = os.stat(path)
            self._last_mtime = st[8] if len(st) > 8 else None
        except Exception:
            pass

    def loop(self):
        if not bus.shared.get("jpeg_enable", True):
            return

        path = bus.shared.get("jpeg_path")
        if not path:
            return

        if not self._should_push(path):
            return

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
                        bus.shared.setdefault("task_errors", {})["jpeg_input"] = "jpeg too large for max_jpeg_bytes"
                except Exception:
                    pass
        except Exception as e:
            bus.shared.setdefault("task_errors", {})["jpeg_input"] = str(e)
            return

        self._pipe.pack_in_header(wv, n, 0, 0, 0)
        self._hub.commit()
        self._last_push_ms = time.ticks_ms()
        self._update_file_state(path)
        bus.shared["jpeg_force_reload"] = False
        st = bus.shared.get("jpeg_state") or {}
        st["in_seq"] = (st.get("in_seq", 0) + 1) & 0xFFFF
        bus.shared["jpeg_state"] = st

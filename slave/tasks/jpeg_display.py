import time

from lib.task import Task
from lib.sys_bus import bus
from lib.jpeg_pipe import ensure_jpeg_pipe


class JpegDisplayTask(Task):
    def on_start(self):
        super().on_start()
        self._pipe = ensure_jpeg_pipe(self.ctx)
        self._hub = self._pipe.jpeg_blocks
        self._lcd = None
        self._displayed_blocks = 0
        self._idle_next_ms = time.ticks_ms()
        bus.register_provider("jpeg_display_blocks", lambda: self._displayed_blocks)

    def _resolve_lcd(self):
        if self._lcd is not None:
            return self._lcd
        lcd = self.ctx.get("lcd")
        if lcd is None:
            lcd = bus.get_service("lcd")
        self._lcd = lcd
        return self._lcd

    def _idle_gate(self, ms):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._idle_next_ms) < 0:
            return False
        self._idle_next_ms = time.ticks_add(now, ms)
        return True

    def loop(self):
        if not bus.shared.get("jpeg_enable", True):
            return

        rv = self._hub.get_read_view()
        if rv is None:
            if self._idle_gate(10):
                pass
            return

        payload_len, x, y, w, h, flags, fmt = self._pipe.unpack_block_header(rv)
        payload = rv[16 : 16 + payload_len]

        lcd = self._resolve_lcd()
        if lcd is not None:
            try:
                lcd.set_window(x, y, x + w - 1, y + h - 1)
                lcd.write_data(payload)
            except Exception as e:
                bus.shared.setdefault("task_errors", {})["jpeg_display"] = str(e)
                self._lcd = None
                return

        self._displayed_blocks += 1

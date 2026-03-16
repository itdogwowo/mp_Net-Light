import time

from lib.task import Task
from lib.sys_bus import bus


class RenderTask(Task):
    def on_start(self):
        super().on_start()
        self._st = self.ctx["st_LED"]
        self._fps = int(self.ctx.get("render_fps") or self.ctx.get("bus_sys", {}).get("local_fps", 40) or 40)
        if self._fps <= 0:
            self._fps = 40
        self._interval_us = (1000 // self._fps) * 1000
        self._next_tick_us = time.ticks_us()
        self._hub = None
        self._render_count = 0
        self._frame_size = len(self._st.big_buffer)
        self._raw_view = self._st.big_buffer
        self._current_big_buffer = None
        self._buff_offset = 0
        self._idle_next_ms = time.ticks_ms()
        self._last_streaming = bool(bus.shared.get("is_streaming"))
        self._last_paused = bool(bus.shared.get("is_paused"))
        bus.register_provider("render_fps", lambda: self._render_count)

    def loop(self):
        if self._hub is None:
            self._hub = bus.get_service("pixel_stream")
            if self._hub is None:
                return
            bus.shared["core1_ready"] = True

        streaming = bool(bus.shared.get("is_streaming"))
        paused = bool(bus.shared.get("is_paused"))

        if (not streaming) or paused:
            now_ms = time.ticks_ms()
            if time.ticks_diff(now_ms, self._idle_next_ms) < 0:
                return
            self._idle_next_ms = time.ticks_add(now_ms, 100 if (not streaming) else 50)
            self._next_tick_us = time.ticks_us()
            self._render_count = 0
            if (not streaming) and (self._last_streaming or (bus.shared.get("is_ready") is False)):
                self._raw_view[:] = bytearray(self._frame_size)
                self._st.show_all()
            self._last_streaming = streaming
            self._last_paused = paused
            return

        now = time.ticks_us()
        if time.ticks_diff(now, self._next_tick_us) < 0:
            return

        if self._current_big_buffer is None or self._buff_offset + self._frame_size > len(self._current_big_buffer):
            self._current_big_buffer = self._hub.get_read_view()
            self._buff_offset = 0

        if self._current_big_buffer:
            self._raw_view[:] = self._current_big_buffer[self._buff_offset : self._buff_offset + self._frame_size]
            self._st.show_all()
            self._render_count += 1
            self._buff_offset += self._frame_size

        self._next_tick_us = time.ticks_add(self._next_tick_us, self._interval_us)


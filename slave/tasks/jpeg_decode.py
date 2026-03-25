import time

from lib.task import Task
from lib.sys_bus import bus
from lib.jpeg_pipe import ensure_jpeg_pipe


class JpegDecodeTask(Task):
    def on_start(self):
        super().on_start()
        self._pipe = ensure_jpeg_pipe(self.ctx)
        self._in_hub = self._pipe.jpeg_in
        self._out_hub = self._pipe.jpeg_blocks
        self._decoder = None
        self._idle_next_ms = time.ticks_ms()
        self._decoded_blocks = 0
        bus.register_provider("jpeg_blocks", lambda: self._decoded_blocks)

    def _ensure_decoder(self):
        if self._decoder is not None:
            return True
        try:
            import jpeg

            cfg = bus.shared.get("JPEG") or {}
            rotation = int(cfg.get("rotation", 0) or 0)
            pixel_format = cfg.get("pixel_format", self._pipe.pixel_format)
            self._decoder = jpeg.Decoder(rotation=rotation, pixel_format=pixel_format, block=True)
            self._fmt = self._pipe.fmt_code()
            return True
        except Exception as e:
            bus.shared.setdefault("task_errors", {})["jpeg_decode"] = str(e)
            return False

    def _wait_out_slot(self):
        wv = self._out_hub.get_write_view()
        if wv is not None:
            return wv
        now = time.ticks_ms()
        if time.ticks_diff(now, self._idle_next_ms) < 0:
            return None
        self._idle_next_ms = time.ticks_add(now, 1)
        return None

    def loop(self):
        if not bus.shared.get("jpeg_enable", True):
            return

        if not self._ensure_decoder():
            return

        rv = self._in_hub.get_read_view()
        if rv is None:
            return

        n, x0, y0, _ = self._pipe.unpack_in_header(rv)
        if not n:
            return

        jpeg_data = rv[12 : 12 + n]

        try:
            info = self._decoder.get_img_info(jpeg_data)
            w = int(info[0])
            h = int(info[1])
            if len(info) >= 4:
                blocks = int(info[2])
                block_h = int(info[3])
            else:
                block_h = 16
                blocks = (h + block_h - 1) // block_h
        except Exception as e:
            bus.shared.setdefault("task_errors", {})["jpeg_decode"] = str(e)
            return

        if w > self._pipe.max_width or block_h > self._pipe.max_block_h:
            bus.shared.setdefault("task_errors", {})["jpeg_decode"] = "image too large for jpeg pipe"
            return

        seq = self._pipe.next_seq()
        st = bus.shared.get("jpeg_state") or {}
        st.update({"out_seq": seq, "w": w, "h": h, "block_h": block_h})
        bus.shared["jpeg_state"] = st

        y = 0
        bpp = self._pipe.bytes_per_pixel
        x0 = int(x0)
        y0 = int(y0)

        for i in range(blocks):
            try:
                blk = self._decoder.decode(jpeg_data)
            except Exception as e:
                bus.shared.setdefault("task_errors", {})["jpeg_decode"] = str(e)
                return

            if blk is None:
                bus.shared.setdefault("task_errors", {})["jpeg_decode"] = "decoder returned None"
                return

            remaining = h - y
            h_this = block_h if remaining >= block_h else remaining
            payload_len = w * h_this * bpp

            wv = None
            while wv is None and bus.shared.get("engine_run", True):
                wv = self._wait_out_slot()
                if wv is None:
                    time.sleep_ms(0)

            if wv is None:
                return

            flags = 0
            if i == 0:
                flags |= 1
            if i == blocks - 1:
                flags |= 2

            self._pipe.pack_block_header(wv, payload_len, x0, y0 + y, w, h_this, flags, self._fmt)

            mv = memoryview(blk)
            wv[16 : 16 + payload_len] = mv[:payload_len]
            self._out_hub.commit()

            y += h_this
            self._decoded_blocks += 1

        stats = bus.shared.get("jpeg_stats") or {}
        stats["last_ms"] = time.ticks_ms()
        stats["last_w"] = w
        stats["last_h"] = h
        stats["last_blocks"] = blocks
        stats["last_seq"] = seq
        bus.shared["jpeg_stats"] = stats

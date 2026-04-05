import time
from lib.task import Task
from lib.sys_bus import bus
from lib.display_service import ensure_display_service, service_error
from lib.jpeg_service import HDR_OUT, unpack_block_header


class DisplayTask(Task):
    def on_start(self):
        super().on_start()
        self._svc = ensure_display_service(bus)
        self._lcd = None
        self._jpeg = None
        self._post = None
        self._swap_buf = None

    def _resolve_lcd(self):
        if self._lcd is not None:
            return self._lcd
        lcd = bus.get_service("lcd")
        if lcd is None:
            lcd = bus.get_service("tft")
        self._lcd = lcd
        return lcd

    def _resolve_jpeg(self):
        if self._jpeg is not None:
            return self._jpeg
        svc = bus.get_service("jpeg_decoder")
        if svc is None:
            svc = bus.get_service("jepg_decoder")
        self._jpeg = svc
        return svc

    def _resolve_post(self):
        if self._post is not None:
            return self._post
        svc = bus.get_service("jpeg_post")
        self._post = svc
        return svc

    def loop(self):
        if not self.running:
            return
        self._svc = bus.get_service("display") or self._svc
        if not self._svc or not self._svc.get("enable", True):
            return

        lcd = self._resolve_lcd()
        if lcd is None:
            return

        jpeg = self._resolve_jpeg()
        if jpeg is None or not jpeg.get("enable"):
            return

        post = self._resolve_post()
        if post is not None and post.get("enable", True) and (post.get("output") or []):
            outs = post.get("output") or []
            use_post = True
        else:
            outs = jpeg.get("output") or []
            use_post = False
        n = len(outs)
        if n <= 0:
            return

        rr = int(self._svc.get("rr", 0) or 0)
        drew = 0

        for off in range(n):
            i = (rr + off) % n
            out = outs[i]
            if not out or not out.get("enabled", True):
                continue
            hub = out.get("hub") if use_post else out.get("block_hub")
            if hub is None:
                continue
            rv = hub.get_read_view()
            if rv is None:
                continue

            try:
                payload_len, seq, x, y, w, h, flags, fmt = unpack_block_header(rv)
                if payload_len <= 0:
                    try:
                        hub.release_read()
                    except Exception:
                        pass
                    continue
                if bool(self._svc.get("full_frame_only", False)):
                    if not ((int(flags) & 1) and (int(flags) & 2)):
                        try:
                            hub.release_read()
                        except Exception:
                            pass
                        continue
                payload = rv[HDR_OUT : HDR_OUT + payload_len]
                hook = self._svc.get("hook", None)
                if bool(self._svc.get("hook_enable", False)) and hook is not None:
                    info = {
                        "label": str(out.get("label") or ""),
                        "seq": int(seq),
                        "x": int(x),
                        "y": int(y),
                        "w": int(w),
                        "h": int(h),
                        "flags": int(flags),
                        "fmt": int(fmt),
                        "pixel_format": str(jpeg.get("pixel_format") or ""),
                    }
                    try:
                        new_payload = hook(payload, info)
                        if new_payload is not None:
                            if int(len(new_payload)) != int(payload_len):
                                raise ValueError("hook payload length mismatch")
                            payload = new_payload
                    except Exception as e:
                        try:
                            hub.release_read()
                        except Exception:
                            pass
                        service_error(self._svc, e)
                        return
                lcd.set_window(int(x), int(y), int(x) + int(w) - 1, int(y) + int(h) - 1)
                pf = str(jpeg.get("pixel_format") or "")
                if pf.endswith("_LE") and (int(payload_len) & 1) == 0:
                    if self._swap_buf is None or len(self._swap_buf) < int(payload_len):
                        self._swap_buf = bytearray(int(payload_len))
                    sb = self._swap_buf
                    j = 0
                    while j < int(payload_len):
                        b0 = payload[j]
                        sb[j] = payload[j + 1]
                        sb[j + 1] = b0
                        j += 2
                    lcd.write_data(memoryview(sb)[: int(payload_len)])
                else:
                    lcd.write_data(payload)
                self._svc["displayed_blocks"] = int(self._svc.get("displayed_blocks", 0) or 0) + 1
                self._svc["last_ms"] = time.ticks_ms()
                drew += 1
                self._svc["rr"] = (i + 1) % n
                try:
                    hub.release_read()
                except Exception:
                    pass
                break
            except Exception as e:
                try:
                    hub.release_read()
                except Exception:
                    pass
                service_error(self._svc, e)
                self._lcd = None
                return

        if drew:
            return

    def on_stop(self):
        super().on_stop()
        self._lcd = None
        self._jpeg = None
        self._post = None

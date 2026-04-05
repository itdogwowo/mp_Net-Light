import time

from lib.task import Task
from lib.sys_bus import bus
from lib.jpeg_service import HDR_OUT, unpack_block_header
from lib.jpeg_post_service import (
    ensure_jpeg_post_service,
    configure_from_jpeg_service,
    get_output_entry,
    get_state_entry,
    pack_full_frame,
)


class JpegPostTask(Task):
    def on_start(self):
        super().on_start()
        self._jpeg = None
        self._post = ensure_jpeg_post_service(bus)
        self._seen_jpeg_epoch = None
        self._framebuf = {}
        self._frame_meta = {}

    def _resolve_jpeg(self):
        if self._jpeg is not None:
            return self._jpeg
        svc = bus.get_service("jpeg_decoder")
        if svc is None:
            svc = bus.get_service("jepg_decoder")
        self._jpeg = svc
        return svc

    def _ensure_config(self, jpeg):
        epoch = int(jpeg.get("cfg_epoch", 0) or 0)
        if self._seen_jpeg_epoch == epoch and (self._post.get("output") or []):
            return True
        self._seen_jpeg_epoch = epoch
        configure_from_jpeg_service(bus, jpeg, name="jpeg_post")
        self._framebuf = {}
        self._frame_meta = {}
        outs = jpeg.get("output") or []
        for it in outs:
            try:
                label = str(it.get("label") or "")
                if not label or not it.get("enabled", True):
                    continue
                fb = it.get("framebuf", None)
                rect = it.get("rect") or {}
                meta = it.get("meta") or {}
                w = int(rect.get("w", 0) or 0)
                h = int(rect.get("h", 0) or 0)
                bpp = int(meta.get("bpp", 2) or 2)
                if fb is None or w <= 0 or h <= 0 or bpp <= 0:
                    continue
                self._framebuf[label] = fb
                self._frame_meta[label] = {"w": w, "h": h, "bpp": bpp, "x": int(rect.get("x", 0) or 0), "y": int(rect.get("y", 0) or 0)}
            except Exception:
                pass
        return True

    def _copy_block_into_frame(self, label, payload, *, x, y, w, h):
        meta = self._frame_meta.get(label, None)
        fb = self._framebuf.get(label, None)
        if meta is None or fb is None:
            return False
        fw = int(meta["w"])
        fh = int(meta["h"])
        bpp = int(meta["bpp"])
        x0 = int(meta["x"])
        y0 = int(meta["y"])

        ox = int(x) - x0
        oy = int(y) - y0
        if ox < 0 or oy < 0 or ox + int(w) > fw or oy + int(h) > fh:
            return False
        row_bytes = int(w) * bpp
        if int(len(payload)) < row_bytes * int(h):
            return False

        dst_stride = fw * bpp
        src = memoryview(payload)
        dst = memoryview(fb)
        dy = 0
        while dy < int(h):
            di = (oy + dy) * dst_stride + ox * bpp
            si = dy * row_bytes
            dst[di : di + row_bytes] = src[si : si + row_bytes]
            dy += 1
        return True

    def _emit_full_frame(self, label, *, seq, fmt_code):
        out = get_output_entry(self._post, label)
        if out is None or not out.get("enabled", True):
            return
        hub = out.get("hub")
        if hub is None:
            return
        wv = hub.get_write_view()
        if wv is None:
            return
        rect = out.get("rect") or {}
        x = int(rect.get("x", 0) or 0)
        y = int(rect.get("y", 0) or 0)
        w = int(rect.get("w", 0) or 0)
        h = int(rect.get("h", 0) or 0)
        frame_bytes = int(out.get("frame_bytes", 0) or 0)
        fb = self._framebuf.get(label, None)
        if fb is None or frame_bytes <= 0:
            return

        payload = memoryview(fb)
        hook = self._post.get("hook", None)
        if bool(self._post.get("hook_enable", False)) and hook is not None:
            info = {"label": label, "seq": int(seq), "x": int(x), "y": int(y), "w": int(w), "h": int(h), "fmt_code": int(fmt_code)}
            payload2 = hook(payload, info)
            if payload2 is not None:
                if int(len(payload2)) != frame_bytes:
                    raise ValueError("jpeg_post hook payload length mismatch")
                payload = payload2

        pack_full_frame(wv, frame_bytes, seq=int(seq), x=int(x), y=int(y), w=int(w), h=int(h), fmt_code=int(fmt_code))
        wv[HDR_OUT : HDR_OUT + frame_bytes] = memoryview(payload)[:frame_bytes]
        hub.commit()

        st = get_state_entry(self._post, label)
        if st is not None:
            st["frames"] = int(st.get("frames", 0) or 0) + 1
            st["last_seq"] = int(seq)
            st["last_ms"] = time.ticks_ms()
            st["last_err"] = ""
        try:
            bus.shared["jpeg_post_last_done"] = {"label": str(label), "seq": int(seq), "ms": time.ticks_ms()}
        except Exception:
            pass

    def _emit_full_frame_from_payload(self, label, payload, *, seq, fmt_code):
        out = get_output_entry(self._post, label)
        if out is None or not out.get("enabled", True):
            return
        hub = out.get("hub")
        if hub is None:
            return
        wv = hub.get_write_view()
        if wv is None:
            return
        rect = out.get("rect") or {}
        x = int(rect.get("x", 0) or 0)
        y = int(rect.get("y", 0) or 0)
        w = int(rect.get("w", 0) or 0)
        h = int(rect.get("h", 0) or 0)
        frame_bytes = int(out.get("frame_bytes", 0) or 0)
        if frame_bytes <= 0 or int(len(payload)) < frame_bytes:
            return

        payload2 = payload
        hook = self._post.get("hook", None)
        if bool(self._post.get("hook_enable", False)) and hook is not None:
            info = {"label": label, "seq": int(seq), "x": int(x), "y": int(y), "w": int(w), "h": int(h), "fmt_code": int(fmt_code)}
            p3 = hook(payload2, info)
            if p3 is not None:
                if int(len(p3)) != frame_bytes:
                    raise ValueError("jpeg_post hook payload length mismatch")
                payload2 = p3

        pack_full_frame(wv, frame_bytes, seq=int(seq), x=int(x), y=int(y), w=int(w), h=int(h), fmt_code=int(fmt_code))
        wv[HDR_OUT : HDR_OUT + frame_bytes] = memoryview(payload2)[:frame_bytes]
        hub.commit()

        st = get_state_entry(self._post, label)
        if st is not None:
            st["frames"] = int(st.get("frames", 0) or 0) + 1
            st["last_seq"] = int(seq)
            st["last_ms"] = time.ticks_ms()
            st["last_err"] = ""
        try:
            bus.shared["jpeg_post_last_done"] = {"label": str(label), "seq": int(seq), "ms": time.ticks_ms()}
        except Exception:
            pass

    def loop(self):
        if not self.running:
            return
        jpeg = self._resolve_jpeg()
        if jpeg is None or not jpeg.get("enable"):
            return
        if not self._post or not self._post.get("enable", True):
            return
        self._ensure_config(jpeg)

        outs = jpeg.get("output") or []
        n = len(outs)
        if n <= 0:
            return

        rr = int(self._post.get("rr", 0) or 0)
        for off in range(n):
            i = (rr + off) % n
            out = outs[i]
            if not out or not out.get("enabled", True):
                continue
            label = str(out.get("label") or "")
            hub = out.get("block_hub")
            if not label or hub is None:
                continue
            rv = hub.get_read_view()
            if rv is None:
                continue

            try:
                payload_len, seq, x, y, w, h, flags, fmt = unpack_block_header(rv)
                if payload_len <= 0:
                    hub.release_read()
                    continue
                payload = rv[HDR_OUT : HDR_OUT + payload_len]

                if (int(flags) & 1) and (int(flags) & 2):
                    try:
                        self._emit_full_frame_from_payload(label, payload, seq=int(seq), fmt_code=int(fmt))
                    except Exception as e:
                        st = get_state_entry(self._post, label)
                        if st is not None:
                            st["last_err"] = str(e)
                            st["last_ms"] = time.ticks_ms()
                    hub.release_read()
                    self._post["rr"] = (i + 1) % n
                    return

                if int(flags) & 1:
                    st = get_state_entry(self._post, label)
                    if st is not None:
                        st["last_err"] = ""

                ok = self._copy_block_into_frame(label, payload, x=int(x), y=int(y), w=int(w), h=int(h))
                hub.release_read()
                if not ok:
                    st = get_state_entry(self._post, label)
                    if st is not None:
                        st["last_err"] = "block copy mismatch"
                        st["last_ms"] = time.ticks_ms()
                    continue

                if int(flags) & 2:
                    try:
                        self._emit_full_frame(label, seq=int(seq), fmt_code=int(fmt))
                    except Exception as e:
                        st = get_state_entry(self._post, label)
                        if st is not None:
                            st["last_err"] = str(e)
                            st["last_ms"] = time.ticks_ms()
                    self._post["rr"] = (i + 1) % n
                    return
                self._post["rr"] = (i + 1) % n
                return
            except Exception as e:
                try:
                    hub.release_read()
                except Exception:
                    pass
                try:
                    self._post["last_err"] = str(e)
                    self._post["last_ms"] = time.ticks_ms()
                except Exception:
                    pass
                return

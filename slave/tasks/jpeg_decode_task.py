import time
from lib.task import Task
from lib.sys_bus import bus
from lib.jpeg_service import HDR_IN, HDR_OUT, IN_STRUCT, OUT_STRUCT, ensure_jpeg_service, get_output_entry, get_state_entry


class JpegDecodeTask(Task):
    def on_start(self):
        super().on_start()
        self._svc = ensure_jpeg_service(bus)
        self._seen_epoch = None
        self._decoder = None
        self._job = None
        self._last_idle_log_ms = 0

    def _set_error(self, label, msg):
        st = get_state_entry(self._svc, label)
        if st is not None:
            st["last_err"] = str(msg)
            st["last_ms"] = time.ticks_ms()
            st["busy"] = 0

    def _ensure_decoder(self, label):
        if self._decoder is not None:
            return True
        try:
            import jpeg

            rotation = int(self._svc.get("rotation", 0) or 0)
            pixel_format = self._svc.get("pixel_format") or "RGB565_LE"
            block = bool(self._svc.get("block", True))
            return_bytes = bool(self._svc.get("return_bytes", False))
            if block and rotation:
                self._set_error(label, "block mode does not support rotation")
                return False
            self._decoder = jpeg.Decoder(rotation=rotation, pixel_format=pixel_format, block=block, return_bytes=return_bytes)
            return True
        except Exception as e:
            self._set_error(label, e)
            return False

    def _pick_job(self):
        src = self._svc.get("source") or []
        n = len(src)
        if n <= 0:
            return None

        rr = int(self._svc.get("_rr", 0) or 0)
        max_jpeg_bytes = int(self._svc.get("max_jpeg_bytes", 0) or 0)

        for off in range(n):
            i = (rr + off) % n
            it = src[i]
            if not it or not it.get("enabled", True):
                continue
            hub = it.get("hub")
            if hub is None:
                continue
            rv = hub.get_read_view()
            if rv is None:
                continue

            try:
                payload_len, seq, x0, y0, flags, fmt_code, path_hash = IN_STRUCT.unpack_from(rv, 0)
            except Exception:
                hub.release_read()
                continue

            label = it.get("label") or ""
            if payload_len <= 0 or (max_jpeg_bytes and payload_len > max_jpeg_bytes):
                self._set_error(label, "jpeg payload too large")
                hub.release_read()
                continue

            st = get_state_entry(self._svc, label)
            if st is None:
                hub.release_read()
                continue

            force = (int(flags or 0) & 1) != 0
            last_hash = int(st.get("last_path_hash", 0) or 0)
            if not force and path_hash and last_hash == int(path_hash):
                st["skipped"] = int(st.get("skipped", 0) or 0) + 1
                st["last_ms"] = time.ticks_ms()
                hub.release_read()
                continue

            jpeg_data = rv[HDR_IN : HDR_IN + payload_len]
            out_label = it.get("route_to") or label
            out = get_output_entry(self._svc, out_label)
            if out is None:
                self._set_error(label, "output label not found")
                hub.release_read()
                continue

            meta = out.get("meta") or {}
            bpp = int(meta.get("bpp", 2) or 2)

            st["busy"] = 1
            st["last_err"] = ""
            self._svc["_rr"] = (i + 1) % n
            self._job = {
                "label": label,
                "out_label": out_label,
                "src_hub": hub,
                "src_view": rv,
                "jpeg_data": jpeg_data,
                "seq": int(seq or 0),
                "x0": int(x0 or 0),
                "y0": int(y0 or 0),
                "flags": int(flags or 0),
                "fmt_code": int(fmt_code or 0),
                "path_hash": int(path_hash or 0),
                "bpp": bpp,
                "info_ok": False,
                "w": 0,
                "h": 0,
                "blocks": 0,
                "block_h": 0,
                "bi": 0,
                "y": 0,
            }
            return self._job

        return None

    def _finish_job(self, ok=True, err=None):
        job = self._job
        if job is None:
            return
        label = job["label"]
        st = get_state_entry(self._svc, label)
        if st is not None:
            st["busy"] = 0
            st["last_ms"] = time.ticks_ms()
            if ok:
                st["decoded_frames"] = int(st.get("decoded_frames", 0) or 0) + 1
                st["last_path_hash"] = int(job.get("path_hash", 0) or 0)
                st["last_err"] = ""
            else:
                st["last_err"] = str(err or "decode error")

        out = get_output_entry(self._svc, job["out_label"])
        if out is not None:
            meta = out.get("meta") or {}
            meta["w"] = int(job.get("w", 0) or 0)
            meta["h"] = int(job.get("h", 0) or 0)
            meta["seq"] = int(job.get("seq", 0) or 0)
            meta["x0"] = int(job.get("x0", 0) or 0)
            meta["y0"] = int(job.get("y0", 0) or 0)
            out["meta"] = meta
            if ok:
                try:
                    bus.shared["jpeg_last_done"] = {
                        "label": str(job.get("out_label") or label),
                        "seq": int(job.get("seq", 0) or 0),
                        "w": int(job.get("w", 0) or 0),
                        "h": int(job.get("h", 0) or 0),
                        "ms": time.ticks_ms(),
                    }
                except Exception:
                    pass
                if bool(self._svc.get("log_done", False)):
                    try:
                        print(
                            f"🖼️ [JPEG] Decoded frame label={job.get('out_label') or label} seq={int(job.get('seq', 0) or 0)} {int(job.get('w', 0) or 0)}x{int(job.get('h', 0) or 0)}"
                        )
                    except Exception:
                        pass

        try:
            job["src_hub"].release_read()
        except Exception:
            pass
        self._job = None

    def _ensure_info(self):
        job = self._job
        if job is None or job.get("info_ok"):
            return True
        try:
            info = self._decoder.get_img_info(job["jpeg_data"])
            w = int(info[0])
            h = int(info[1])
            blocks = 1
            block_h = h
            if bool(self._svc.get("block", True)):
                if len(info) >= 4:
                    blocks = int(info[2])
                    block_h = int(info[3])
                else:
                    block_h = 16
                    blocks = (h + block_h - 1) // block_h
            job["w"] = w
            job["h"] = h
            job["blocks"] = blocks
            job["block_h"] = block_h
            job["info_ok"] = True
            return True
        except Exception as e:
            self._finish_job(ok=False, err=e)
            return False

    def _step_block_mode(self):
        job = self._job
        out = get_output_entry(self._svc, job["out_label"])
        out_hub = None if out is None else out.get("block_hub")
        if out_hub is None:
            self._finish_job(ok=False, err="block_hub missing")
            return

        exchange_full_frame = bool(self._svc.get("exchange_full_frame", True))
        framebuf = None if out is None else out.get("framebuf")
        rect = {} if out is None else (out.get("rect") or {})
        fw = int(rect.get("w", 0) or 0)
        fh = int(rect.get("h", 0) or 0)
        if exchange_full_frame:
            if framebuf is None:
                self._finish_job(ok=False, err="framebuf missing")
                return
            if fw <= 0 or fh <= 0:
                self._finish_job(ok=False, err="rect missing")
                return

        step_blocks = int(self._svc.get("step_blocks", 0) or 0)
        if step_blocks <= 0:
            step_blocks = int(job.get("blocks", 1) or 1) - int(job.get("bi", 0) or 0)
            if step_blocks <= 0:
                step_blocks = 1

        st = get_state_entry(self._svc, job["label"])

        for _ in range(step_blocks):
            if int(job["bi"]) >= int(job["blocks"]):
                break

            try:
                blk = self._decoder.decode(job["jpeg_data"])
            except Exception as e:
                self._finish_job(ok=False, err=e)
                return

            if blk is None:
                job["bi"] = job["blocks"]
                break

            remaining = int(job["h"]) - int(job["y"])
            h_this = int(job["block_h"]) if remaining >= int(job["block_h"]) else remaining
            if h_this <= 0:
                job["bi"] = job["blocks"]
                break

            payload_len = int(job["w"]) * int(h_this) * int(job["bpp"])

            mv = memoryview(blk)
            if exchange_full_frame:
                if int(job["w"]) != fw or int(job["h"]) != fh:
                    self._finish_job(ok=False, err="img size mismatch rect")
                    return
                row_bytes = int(job["w"]) * int(job["bpp"])
                dst_stride = fw * int(job["bpp"])
                dst = memoryview(framebuf)
                src = mv[:payload_len]
                dy = 0
                while dy < int(h_this):
                    di = (int(job["y"]) + dy) * dst_stride
                    si = dy * row_bytes
                    dst[di : di + row_bytes] = src[si : si + row_bytes]
                    dy += 1
            else:
                wv = out_hub.get_write_view()
                if wv is None:
                    return
                out_flags = 0
                if int(job["bi"]) == 0:
                    out_flags |= 1
                if int(job["bi"]) == int(job["blocks"]) - 1:
                    out_flags |= 2
                OUT_STRUCT.pack_into(
                    wv,
                    0,
                    payload_len,
                    int(job["seq"]),
                    int(job["x0"]),
                    int(job["y0"]) + int(job["y"]),
                    int(job["w"]),
                    int(h_this),
                    int(out_flags),
                    int(job["fmt_code"]),
                )
                wv[HDR_OUT : HDR_OUT + payload_len] = mv[:payload_len]
                out_hub.commit()

            job["y"] = int(job["y"]) + int(h_this)
            job["bi"] = int(job["bi"]) + 1
            if st is not None:
                st["decoded_blocks"] = int(st.get("decoded_blocks", 0) or 0) + 1

        if int(job["bi"]) >= int(job["blocks"]):
            if exchange_full_frame:
                wv = out_hub.get_write_view()
                if wv is None:
                    self._finish_job(ok=False, err="output hub full")
                    return
                payload_len = int(job["w"]) * int(job["h"]) * int(job["bpp"])
                OUT_STRUCT.pack_into(
                    wv,
                    0,
                    payload_len,
                    int(job["seq"]),
                    int(job["x0"]),
                    int(job["y0"]),
                    int(job["w"]),
                    int(job["h"]),
                    3,
                    int(job["fmt_code"]),
                )
                wv[HDR_OUT : HDR_OUT + payload_len] = memoryview(framebuf)[:payload_len]
                out_hub.commit()
            self._finish_job(ok=True)

    def _step_full_mode(self):
        job = self._job
        out = get_output_entry(self._svc, job["out_label"])
        out_hub = None if out is None else out.get("block_hub")
        if out_hub is None:
            self._finish_job(ok=False, err="block_hub missing")
            return
        wv = out_hub.get_write_view()
        if wv is None:
            return
        try:
            img = self._decoder.decode(job["jpeg_data"])
        except Exception as e:
            self._finish_job(ok=False, err=e)
            return
        if img is None:
            self._finish_job(ok=False, err="decoder returned None")
            return
        w = int(job.get("w", 0) or 0)
        h = int(job.get("h", 0) or 0)
        payload_len = w * h * int(job["bpp"])
        OUT_STRUCT.pack_into(
            wv,
            0,
            payload_len,
            int(job["seq"]),
            int(job["x0"]),
            int(job["y0"]),
            int(w),
            int(h),
            3,
            int(job["fmt_code"]),
        )
        mv = memoryview(img)
        wv[HDR_OUT : HDR_OUT + payload_len] = mv[:payload_len]
        out_hub.commit()
        st = get_state_entry(self._svc, job["label"])
        if st is not None:
            st["decoded_blocks"] = int(st.get("decoded_blocks", 0) or 0) + 1
        self._finish_job(ok=True)

    def loop(self):
        if not self.running:
            return
        self._svc = bus.get_service("jpeg_decoder") or bus.get_service("jepg_decoder") or self._svc
        if not self._svc or not self._svc.get("enable"):
            return

        epoch = int(self._svc.get("cfg_epoch", 0) or 0)
        if self._seen_epoch != epoch:
            self._seen_epoch = epoch
            self._decoder = None
            self._job = None

        if self._job is None:
            self._pick_job()
            if self._job is None:
                now = time.ticks_ms()
                if time.ticks_diff(now, int(self._last_idle_log_ms or 0)) > 1000:
                    self._last_idle_log_ms = now
                    try:
                        src = self._svc.get("source") or []
                        st = self._svc.get("state") or []
                        fills = []
                        for it in src:
                            try:
                                hub = it.get("hub")
                                fills.append((str(it.get("label") or ""), hub.get_fill_level() if hub else -1))
                            except Exception:
                                pass
                        busy = []
                        for s in st:
                            try:
                                busy.append((str(s.get("label") or ""), int(s.get("busy", 0) or 0), str(s.get("last_err") or "")))
                            except Exception:
                                pass
                        print(f"⏳ [JPEG] waiting input fills={fills} state={busy}")
                    except Exception:
                        pass
                return

        if not self._ensure_decoder(self._job["label"]):
            self._finish_job(ok=False, err="decoder init failed")
            return
        if not self._ensure_info():
            return

        if bool(self._svc.get("block", True)):
            self._step_block_mode()
        else:
            self._step_full_mode()

import time

from lib.task import Task
from lib.sys_bus import bus
from lib.fs_manager import fs
from lib.jpeg_service import ensure_jpeg_service, submit_jpeg_file


def _dir_name(path):
    if not path:
        return ""
    path = str(path)
    i = path.rfind("/")
    if i < 0:
        return ""
    return path[:i]


def _try_load_assets_root(dp_path):
    if not dp_path:
        return ""
    try:
        import ujson

        with open(dp_path, "r") as f:
            dp = ujson.load(f) or {}
        if isinstance(dp, dict):
            ar = dp.get("assets_root") or dp.get("root_path") or ""
            return str(ar or "")
    except Exception:
        return ""
    return ""


def _path_exists(p):
    if not p:
        return False
    try:
        import os

        os.stat(p)
        return True
    except Exception:
        return False


class JpegFeedTask(Task):
    def on_start(self):
        super().on_start()
        self._svc = ensure_jpeg_service(bus)
        self._last_epoch = None
        self._did_submit = False
        self._seq = 1
        self._last_log_ms = 0
        try:
            print("🧩 [JPEG_FEED] start")
        except Exception:
            pass

    def _pick_path(self, base_dir, label):
        base_dir = str(base_dir or "")
        label = str(label or "")
        if base_dir.endswith("/"):
            base_dir = base_dir[:-1]

        candidates = []
        p0 = f"{base_dir}/{label}/000.jpeg" if base_dir else f"/{label}/000.jpeg"
        candidates.append(p0)
        candidates.append(f"/jpeg/{label}/000.jpeg")

        for p in candidates:
            try:
                with open(p, "rb"):
                    return p
            except Exception:
                pass

        m = getattr(fs, "manifest", None) or {}
        prefixes = []
        if base_dir:
            prefixes.append(f"{base_dir}/{label}/")
        prefixes.append(f"/jpeg/{label}/")
        prefixes.append(f"/{label}/")
        best = None
        for k in m.keys():
            try:
                ks = str(k)
                ok_prefix = False
                for pre in prefixes:
                    if ks.startswith(pre):
                        ok_prefix = True
                        break
                if not ok_prefix:
                    continue
                low = ks.lower()
                if not (low.endswith(".jpeg") or low.endswith(".jpg")):
                    continue
                if best is None or ks < best:
                    best = ks
            except Exception:
                pass
        return best

    def loop(self):
        if not self.running:
            return

        self._svc = bus.get_service("jpeg_decoder") or bus.get_service("jepg_decoder") or self._svc
        if not self._svc or not self._svc.get("enable"):
            return

        disp_cfg = bus.shared.get("TFT") or bus.shared.get("Display") or {}
        if not disp_cfg.get("enable"):
            return

        feed_cfg = bus.shared.get("JPEG_FEED") or {}
        if int(feed_cfg.get("enable", 1) or 1) == 0:
            return

        epoch = int(self._svc.get("cfg_epoch", 0) or 0)
        if self._last_epoch != epoch:
            self._last_epoch = epoch
            self._did_submit = False

        if self._did_submit:
            return

        dp_path = disp_cfg.get("dp_config_path") or ""
        base_dir = str(feed_cfg.get("assets_root") or "")
        if not base_dir:
            base_dir = _try_load_assets_root(dp_path)
        if not base_dir:
            base_dir = _dir_name(dp_path)
        base_dir = str(base_dir or "")
        if base_dir == "/sd" and not _path_exists("/sd"):
            base_dir = "/jpeg"
        if not base_dir:
            base_dir = "/jpeg"

        labels = []
        src = self._svc.get("source") or []
        for it in src:
            try:
                if it and it.get("enabled", True):
                    labels.append(str(it.get("label") or ""))
            except Exception:
                pass
        if not labels:
            return

        for label in labels:
            if not label:
                continue
            out = None
            try:
                out = (self._svc.get("_idx_output") or {}).get(label, None)
            except Exception:
                out = None

            x0 = 0
            y0 = 0
            try:
                if out is not None:
                    o = (self._svc.get("output") or [])[int(out)]
                    rect = o.get("rect") or {}
                    x0 = int(rect.get("x", 0) or 0)
                    y0 = int(rect.get("y", 0) or 0)
            except Exception:
                pass

            path = self._pick_path(base_dir, label)
            if not path:
                continue
            ok = submit_jpeg_file(self._svc, label, path, seq=self._seq, x0=x0, y0=y0, flags=1)
            if ok:
                try:
                    print(f"🧩 [JPEG_FEED] submit label={label} path={path} seq={int(self._seq)} x0={int(x0)} y0={int(y0)}")
                except Exception:
                    pass
                try:
                    bus.shared["jpeg_feed_debug"] = {
                        "ok": 1,
                        "label": str(label),
                        "path": str(path),
                        "base_dir": str(base_dir),
                        "ms": time.ticks_ms(),
                    }
                except Exception:
                    pass
                self._seq = (int(self._seq) + 1) & 0xFFFF
                self._did_submit = True
                return

        try:
            bus.shared.setdefault("task_errors", {})["jpeg_feed"] = "no jpeg file found under assets_root/label"
        except Exception:
            pass
        now = time.ticks_ms()
        if time.ticks_diff(now, int(self._last_log_ms or 0)) > 1000:
            self._last_log_ms = now
            try:
                print(f"⚠️ [JPEG_FEED] no file base_dir={base_dir} labels={labels}")
            except Exception:
                pass
            try:
                bus.shared["jpeg_feed_debug"] = {
                    "ok": 0,
                    "base_dir": str(base_dir),
                    "labels": [str(x) for x in labels],
                    "dp_config_path": str(disp_cfg.get("dp_config_path") or ""),
                    "has_sd": 1 if _path_exists("/sd") else 0,
                    "has_jpeg_dir": 1 if _path_exists("/jpeg") else 0,
                    "ms": time.ticks_ms(),
                }
            except Exception:
                pass
        time.sleep_ms(200)

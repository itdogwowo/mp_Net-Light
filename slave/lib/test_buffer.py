class RGBWTestPattern:
    def __init__(self, total_pixels, level=64, segment=16, speed=1):
        self.total_pixels = int(total_pixels)
        self.level = int(level)
        self.segment = int(segment)
        self.speed = int(speed)
        self.frame = 0

    def write_into(self, view):
        n = self.total_pixels
        level = self.level & 0xFF
        seg = self.segment
        f = self.frame
        span = seg * 4
        idx = 0
        for i in range(n):
            p = (i + f) % span
            if p < seg:
                r, g, b, w = level, 0, 0, 0
            elif p < seg * 2:
                r, g, b, w = 0, level, 0, 0
            elif p < seg * 3:
                r, g, b, w = 0, 0, level, 0
            else:
                r, g, b, w = 0, 0, 0, level
            view[idx] = r
            view[idx + 1] = g
            view[idx + 2] = b
            view[idx + 3] = w
            idx += 4
        self.frame = (f + self.speed) % span


def make_default_test_pattern(total_bytes, system_cfg=None):
    total_pixels = int(total_bytes // 4)
    level = 64
    segment = 16
    speed = 1
    if isinstance(system_cfg, dict):
        try:
            level = int(system_cfg.get("test_level", level))
        except Exception:
            pass
        try:
            segment = int(system_cfg.get("test_segment", segment))
        except Exception:
            pass
        try:
            speed = int(system_cfg.get("test_speed", speed))
        except Exception:
            pass
    if level < 0:
        level = 0
    if level > 255:
        level = 255
    if segment <= 0:
        segment = 1
    if speed <= 0:
        speed = 1
    return RGBWTestPattern(total_pixels, level=level, segment=segment, speed=speed)


def _build_sine_lut():
    try:
        import math
    except Exception:
        return bytes([0] * 256)
    out = bytearray(256)
    for i in range(256):
        v = int((math.sin((i * 6.283185307179586) / 256.0) + 1.0) * 127.5)
        if v < 0:
            v = 0
        if v > 255:
            v = 255
        out[i] = v
    return bytes(out)


_SINE_LUT = _build_sine_lut()


class RGBWSinePattern:
    def __init__(self, total_pixels, level=127, step=6, speed=2, w_step=3):
        self.total_pixels = int(total_pixels)
        self.level = int(level)
        self.step = int(step)
        self.speed = int(speed)
        self.w_step = int(w_step)
        self.phase = 0
        self.phase_w = 0

    def write_into(self, view):
        n = self.total_pixels
        level = self.level
        if level < 0:
            level = 0
        if level > 255:
            level = 255
        lut = _SINE_LUT
        phase = self.phase & 255
        phase_w = self.phase_w & 255
        step = self.step & 255
        w_step = self.w_step & 255
        idx = 0
        for i in range(n):
            p = (phase + i * step) & 255
            r = (lut[p] * level) // 255
            g = (lut[(p + 85) & 255] * level) // 255
            b = (lut[(p + 170) & 255] * level) // 255
            pw = (phase_w + i * w_step) & 255
            w = (lut[(pw + 64) & 255] * level) // 255
            view[idx] = r
            view[idx + 1] = g
            view[idx + 2] = b
            view[idx + 3] = w
            idx += 4
        self.phase = (phase + (self.speed & 255)) & 255
        w_speed = self.speed // 2
        if w_speed <= 0:
            w_speed = 1
        self.phase_w = (phase_w + (w_speed & 255)) & 255


def make_test_pattern(total_bytes, test_cfg=None):
    total_pixels = int(total_bytes // 4)
    cfg = test_cfg if isinstance(test_cfg, dict) else {}
    pattern = cfg.get("test_pattern", 0)
    if pattern == 1 or pattern == "sine":
        level = 127
        step = 6
        speed = 2
        w_step = 3
        try:
            level = int(cfg.get("test_level", level))
        except Exception:
            pass
        try:
            step = int(cfg.get("test_step", step))
        except Exception:
            pass
        try:
            speed = int(cfg.get("test_speed", speed))
        except Exception:
            pass
        try:
            w_step = int(cfg.get("test_w_step", w_step))
        except Exception:
            pass
        if step <= 0:
            step = 1
        if w_step <= 0:
            w_step = 1
        if speed <= 0:
            speed = 1
        if level < 0:
            level = 0
        if level > 255:
            level = 255
        return RGBWSinePattern(total_pixels, level=level, step=step, speed=speed, w_step=w_step)
    return make_default_test_pattern(total_bytes, cfg)

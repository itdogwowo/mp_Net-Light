try:
    import lvgl as lv
    import lcd_bus
    HAS_LVGL = True
except ImportError:
    HAS_LVGL = False

from lib.dispatch import dprint


class _RGB565PushAdapter:
    def __init__(self, data_bus, *, big_endian=True):
        self._bus = data_bus
        self._big_endian = bool(big_endian)
        self._tx_param = getattr(data_bus, "tx_param", None)
        self._tx_color = getattr(data_bus, "tx_color", None)

    def _u16(self, v):
        v = int(v) & 0xFFFF
        if self._big_endian:
            return bytes([(v >> 8) & 0xFF, v & 0xFF])
        return bytes([v & 0xFF, (v >> 8) & 0xFF])

    def set_window(self, x0, y0, x1, y1):
        if self._tx_param is None:
            raise Exception("lcd_bus missing tx_param")
        self._tx_param(0x2A, self._u16(x0) + self._u16(x1))
        self._tx_param(0x2B, self._u16(y0) + self._u16(y1))
        self._tx_param(0x2C, b"")

    def write_data(self, buf):
        if self._tx_color is None:
            raise Exception("lcd_bus missing tx_color")
        self._tx_color(buf)


def init_display(sysBus):
    disp_cfg = sysBus.shared.get("Display", {})
    if not disp_cfg.get("enable", 0):
        return None

    dprint("🖥️ 初始化顯示器...")

    spi_idx = disp_cfg.get("spi_idx", 0)
    spi_bus_list = sysBus.get_service("spi_bus_list")
    spi_list = sysBus.get_service("spi_list")

    gpio = disp_cfg.get("GPIO", {})
    dc_pin = gpio.get("dc", -1)
    cs_pin = gpio.get("cs", -1)
    rst_pin = gpio.get("rst", -1)
    bl_pin = gpio.get("bl", -1)

    if HAS_LVGL and spi_bus_list and spi_idx < len(spi_bus_list):
        dprint("   - 模式: LVGL (lcd_bus)")
        try:
            try:
                lv.init()
            except Exception:
                pass

            driver_name = disp_cfg.get("driver")
            if driver_name == "gc9a01":
                default_freq = 40_000_000
            else:
                default_freq = 80_000_000
            freq = int(disp_cfg.get("freq", default_freq) or default_freq)
            bus = lcd_bus.SPIBus(
                spi_bus=spi_bus_list[spi_idx],
                dc=dc_pin,
                cs=cs_pin,
                freq=freq
            )

            if driver_name:
                try:
                    import machine

                    mod = __import__(driver_name)
                    cls = getattr(mod, driver_name.upper(), None) or getattr(mod, "GC9A01", None)
                    if cls is not None:
                        w = int(disp_cfg.get("width", 240) or 240)
                        h = int(disp_cfg.get("height", 240) or 240)
                        rot = int(disp_cfg.get("rotation", 0) or 0)
                        bl_state = int(disp_cfg.get("backlight_on_state", 1) or 1)

                        tries = []
                        tries.append(
                            lambda: cls(
                                data_bus=bus,
                                display_width=w,
                                display_height=h,
                                reset_pin=int(rst_pin),
                                backlight_pin=int(bl_pin),
                                backlight_on_state=bl_state,
                                color_space=lv.COLOR_FORMAT.RGB565,
                                rgb565_byte_swap=True,
                            )
                        )
                        tries.append(
                            lambda: cls(
                                data_bus=bus,
                                display_width=w,
                                display_height=h,
                                reset_pin=int(rst_pin),
                                backlight_pin=int(bl_pin),
                                color_space=lv.COLOR_FORMAT.RGB565,
                            )
                        )
                        tries.append(
                            lambda: cls(
                                data_bus=bus,
                                display_width=w,
                                display_height=h,
                                reset_pin=int(rst_pin),
                                backlight_pin=int(bl_pin),
                            )
                        )
                        tries.append(
                            lambda: cls(
                                bus,
                                w,
                                h,
                                reset=machine.Pin(int(rst_pin), machine.Pin.OUT)
                                if rst_pin is not None and int(rst_pin) >= 0
                                else None,
                                cs=machine.Pin(int(cs_pin), machine.Pin.OUT)
                                if cs_pin is not None and int(cs_pin) >= 0
                                else None,
                                dc=machine.Pin(int(dc_pin), machine.Pin.OUT)
                                if dc_pin is not None and int(dc_pin) >= 0
                                else None,
                                backlight=machine.Pin(int(bl_pin), machine.Pin.OUT)
                                if bl_pin is not None and int(bl_pin) >= 0
                                else None,
                                rotation=rot,
                            )
                        )
                        spi = spi_list[spi_idx] if spi_list and spi_idx < len(spi_list) else None
                        if spi is not None:
                            tries.append(
                                lambda: cls(
                                    spi,
                                    w,
                                    h,
                                    reset=machine.Pin(int(rst_pin), machine.Pin.OUT)
                                    if rst_pin is not None and int(rst_pin) >= 0
                                    else None,
                                    cs=machine.Pin(int(cs_pin), machine.Pin.OUT)
                                    if cs_pin is not None and int(cs_pin) >= 0
                                    else None,
                                    dc=machine.Pin(int(dc_pin), machine.Pin.OUT)
                                    if dc_pin is not None and int(dc_pin) >= 0
                                    else None,
                                    backlight=machine.Pin(int(bl_pin), machine.Pin.OUT)
                                    if bl_pin is not None and int(bl_pin) >= 0
                                    else None,
                                    rotation=rot,
                                )
                            )

                        errs = []
                        disp = None
                        for i, ctor in enumerate(tries):
                            try:
                                disp = ctor()
                                break
                            except Exception as e:
                                errs.append((i, str(e)))
                                disp = None

                        if disp is not None:
                            try:
                                disp.init()
                            except Exception:
                                pass
                            sysBus.register_service("lvgl_display", disp)
                        else:
                            sysBus.shared.setdefault("task_errors", {})["display_driver"] = str(errs)
                except Exception as e:
                    sysBus.shared.setdefault("task_errors", {})["display_driver"] = str(e)

            big_endian = (disp_cfg.get("rgb565_endian", "BE") or "BE") != "LE"
            lcd = _RGB565PushAdapter(bus, big_endian=big_endian)
            sysBus.register_service("lcd", lcd)
            sysBus.register_service("lcd_bus", bus)
            sysBus.register_service("lvgl", lv)
            dprint("✓ LVGL Display Ready")
            return lcd
        except Exception as e:
            dprint(f"✗ LVGL Init Failed: {e}")
            return None

    else:
        dprint("   - 模式: Native SPI (No LVGL)")
        spi = None
        if spi_list and spi_idx < len(spi_list):
            spi = spi_list[spi_idx]

        if not spi:
            dprint("✗ No SPI device available")
            return None

        try:
            from lib.simple_lcd import SimpleLCD
            lcd = SimpleLCD(spi, dc=dc_pin, cs=cs_pin, rst=rst_pin, bl=bl_pin, 
                          width=disp_cfg.get("width", 240), 
                          height=disp_cfg.get("height", 240))
            lcd.init()
            sysBus.register_service("lcd", lcd)
            dprint("✓ Native Display Ready")
            return lcd
        except ImportError:
            dprint("⚠️ Missing lib/simple_lcd.py, skipping native display")
            return None

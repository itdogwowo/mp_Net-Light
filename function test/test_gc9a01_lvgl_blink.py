import time

import machine
from machine import Pin

import lvgl as lv
import lcd_bus
import gc9a01


def _try_lv_init():
    try:
        lv.init()
    except Exception:
        pass


class _RGB565PushAdapter:
    def __init__(self, data_bus):
        self._tx_param = getattr(data_bus, "tx_param", None)
        self._tx_color = getattr(data_bus, "tx_color", None)
        self._data_bus = data_bus

    def _u16be(self, v):
        v = int(v) & 0xFFFF
        return bytes([(v >> 8) & 0xFF, v & 0xFF])

    def set_window(self, x0, y0, x1, y1):
        if self._tx_param is None:
            raise Exception("lcd_bus missing tx_param")
        self._tx_param(0x2A, self._u16be(x0) + self._u16be(x1))
        self._tx_param(0x2B, self._u16be(y0) + self._u16be(y1))
        self._tx_param(0x2C, b"")

    def write_data(self, buf):
        if self._tx_color is None:
            raise Exception("lcd_bus missing tx_color")
        self._tx_color(buf)


def _try_make_spi_candidates():
    out = []
    try:
        spi_bus = machine.SPI.Bus(host=2, sck=10, mosi=11)
        out.append(("SPI.Bus", spi_bus))
    except Exception as e:
        out.append(("SPI.Bus:err", e))
    try:
        spi_bus = machine.SPI.Bus(host=2, sck=10, mosi=11)
        try:
            dev = machine.SPI.Device(spi_bus=spi_bus, cs=9, freq=80_000_000, polarity=0, phase=0)
        except Exception:
            dev = machine.SPI.Device(spi_bus=spi_bus, cs=Pin(9, Pin.OUT), freq=80_000_000, polarity=0, phase=0)
        out.append(("SPI.Device", dev))
    except Exception as e:
        out.append(("SPI.Device:err", e))
    return out


def _try_make_lcd_bus(spi_obj):
    try:
        freq = 40_000_000
        return lcd_bus.SPIBus(spi_bus=spi_obj, dc=8, cs=9, freq=freq)
    except Exception as e:
        return e


def _try_make_display(data_bus):
    w = 240
    h = 240
    rst = 14
    bl = 2
    
    import gc9a01
    cls = getattr(gc9a01, "GC9A01", None)
    if cls is None:
        raise Exception("GC9A01 class not found in gc9a01 module")

    errs = []

    try:
        disp = cls(
            data_bus=data_bus,
            display_width=w,
            display_height=h,
            reset_pin=rst,
            backlight_pin=bl,
            color_space=lv.COLOR_FORMAT.RGB565,
        )
        try:
            if hasattr(disp, "set_power"):
                disp.set_power(True)
        except Exception:
            pass
        try:
            disp.init()
        except Exception:
            pass
        return disp
    except Exception as e:
        errs.append(("sig1", e))

    try:
        disp = cls(
            data_bus=data_bus,
            display_width=w,
            display_height=h,
            reset_pin=rst,
            backlight_pin=bl,
        )
        try:
            if hasattr(disp, "set_power"):
                disp.set_power(True)
        except Exception:
            pass
        try:
            disp.init()
        except Exception:
            pass
        return disp
    except Exception as e:
        errs.append(("sig2", e))

    try:
        disp = cls(
            data_bus=data_bus,
            display_width=w,
            display_height=h,
            reset_pin=Pin(rst, Pin.OUT),
            backlight_pin=Pin(bl, Pin.OUT),
            color_space=lv.COLOR_FORMAT.RGB565,
        )
        try:
            if hasattr(disp, "set_power"):
                disp.set_power(True)
        except Exception:
            pass
        try:
            disp.init()
        except Exception:
            pass
        return disp
    except Exception as e:
        errs.append(("sig3", e))

    raise Exception(str(errs))


def _try_make_display_native(spi_obj):
    w = 240
    h = 240
    try:
        disp = gc9a01.GC9A01(
            spi_obj,
            w,
            h,
            dc=Pin(8, Pin.OUT),
        )
        try:
            disp.init()
        except Exception:
            pass
        return disp
    except Exception as e:
        return e


def _screen_active():
    scr = None
    try:
        if hasattr(lv, "screen_active"):
            scr = lv.screen_active()
        else:
            scr = lv.scr_act()
    except Exception:
        scr = None
    return scr


def _screen_load(scr):
    try:
        if hasattr(lv, "screen_load"):
            lv.screen_load(scr)
        else:
            lv.scr_load(scr)
    except Exception:
        pass


def _ensure_screen():
    scr = _screen_active()
    if scr is None:
        try:
            scr = lv.obj()
        except Exception:
            scr = None
    if scr is not None:
        _screen_load(scr)
    return scr


def _ui_pump(ms=5):
    try:
        if hasattr(lv, "tick_inc"):
            lv.tick_inc(ms)
    except Exception:
        pass
    try:
        if hasattr(lv, "timer_handler"):
            lv.timer_handler()
        else:
            lv.task_handler()
    except Exception:
        pass


def main():
    _try_lv_init()

    bl = Pin(2, Pin.OUT)
    bl.value(1)

    spi_cands = _try_make_spi_candidates()

    for name, obj in spi_cands:
        if name.endswith(":err"):
            print(name, obj)
            continue

        data_bus = _try_make_lcd_bus(obj)
        if not isinstance(data_bus, Exception):
            try:
                d = _try_make_display(data_bus)
                print("lvgl+lcd_bus ok via", name, d)
                scr = _ensure_screen()
                if scr is None:
                    raise Exception("lvgl screen is None after display init")
                try:
                    if hasattr(d, "set_power"):
                        d.set_power(True)
                except Exception:
                    pass
                try:
                    if hasattr(d, "set_backlight"):
                        d.set_backlight(100)
                except Exception:
                    pass
                try:
                    if hasattr(d, "set_brightness"):
                        d.set_brightness(100)
                except Exception:
                    pass

                try:
                    import gc

                    print("mem_free:", gc.mem_free())
                except Exception:
                    pass

                try:
                    scr.set_style_bg_color(lv.color_hex(0x00FF00), 0)
                    scr.set_style_bg_opa(lv.OPA.COVER, 0)
                except Exception:
                    pass
                try:
                    label = lv.label(scr)
                    label.set_text("GC9A01 OK")
                    try:
                        label.center()
                    except Exception:
                        pass
                except Exception:
                    pass
                for _ in range(50):
                    _ui_pump(10)
                    time.sleep_ms(10)

                while True:
                    try:
                        bl.value(1)
                    except Exception:
                        pass
                    try:
                        scr.set_style_bg_color(lv.color_hex(0xFF0000), 0)
                        scr.set_style_bg_opa(lv.OPA.COVER, 0)
                    except Exception:
                        pass
                    for _ in range(30):
                        _ui_pump(10)
                        time.sleep_ms(10)
                    time.sleep_ms(300)
                    try:
                        bl.value(0)
                    except Exception:
                        pass
                    try:
                        scr.set_style_bg_color(lv.color_hex(0x000000), 0)
                        scr.set_style_bg_opa(lv.OPA.COVER, 0)
                    except Exception:
                        pass
                    for _ in range(30):
                        _ui_pump(10)
                        time.sleep_ms(10)
                    time.sleep_ms(300)
                break
            except Exception as e:
                print("lvgl+lcd_bus fail via", name, e)

        native = _try_make_display_native(obj)
        if not isinstance(native, Exception):
            print("native ok via", name, native)
            while True:
                try:
                    native.fill(0xF800)
                except Exception:
                    pass
                time.sleep_ms(300)
                try:
                    native.fill(0x0000)
                except Exception:
                    pass
                time.sleep_ms(300)
        else:
            print("native fail via", name, native)
    raise Exception("display init failed")


main()

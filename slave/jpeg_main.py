import time
import _thread

from lib.sys_bus import bus
from lib.task_manager import TaskManager

from tasks.jpeg_input import JpegInputTask
from tasks.jpeg_player import JpegPlayerTask
from tasks.jpeg_decode import JpegDecodeTask
from tasks.jpeg_display import JpegDisplayTask


def launcher():
    bus.shared["engine_run"] = True
    cfg = bus.shared.get("JPEG") or {}
    bus.shared.setdefault("jpeg_enable", bool(cfg.get("enable", 1)))
    bus.shared.setdefault("System", {})

    ctx = {"bus": bus, "bus_sys": bus.shared.get("System") or {}}

    try:
        tm = TaskManager(ctx)
        tm.register_task("jpeg_input", JpegInputTask, affinity=(1, 0))
        tm.register_task("jpeg_player", JpegPlayerTask, affinity=(1, 0))
        tm.register_task("jpeg_decode", JpegDecodeTask, affinity=(0, 1))
        tm.register_task("jpeg_display", JpegDisplayTask, affinity=(1, 0))
        _thread.start_new_thread(tm.runner_loop, (1,))
        tm.runner_loop(0)

    except KeyboardInterrupt:
        print("\n👋 User stop requested.")
    except Exception as e:
        print(f"❌ System Error: {e}")
    finally:
        bus.shared["engine_run"] = False
        time.sleep_ms(200)


if __name__ == "__main__":
    launcher()

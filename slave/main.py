# main.py
import machine, network, time, _thread, ubinascii
from app import App
from lib.sys_bus import bus
from lib.task_manager import TaskManager
from tasks import FSScanTask, RenderTask, NetworkTask, SupplyChainTask, HeartbeatTask
from apa102 import APA102
from lib.fs_manager import fs

def launcher():
    print(f"📂 [FS] Initializing File System Manager...")
    # fs 已經在導入時自動初始化 (load manifest or scan)
    
    st_LED = bus.get_service("st_LED")
    
    # 2. 總線與 ID
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True
    bus_sys = bus.shared["System"]
    test_cfg = bus.shared.get("test_mode") or {}
    if test_cfg.get("enable") == 1 or test_cfg.get("enable") is True:
        bus.shared.update({"is_streaming": True, "is_paused": False, "is_ready": True, "play_mode": 1})
        print("🧪 [MODE] Test mode: auto playback enabled")


    try:

        app = App()
        ctx = {"app": app, "bus": bus, "st_LED": st_LED, "bus_sys": bus_sys}
        tm = TaskManager(ctx)
        tm.register_task("network", NetworkTask, affinity=(1, 0))
        tm.register_task("supply_chain", SupplyChainTask, affinity=(1, 0))
        tm.register_task("heartbeat", HeartbeatTask, affinity=(1, 0))
        tm.register_task("render", RenderTask, affinity=(0, 1))
        tm.register_task("fs_scan", FSScanTask, affinity=(0, 1))
        _thread.start_new_thread(tm.runner_loop, (1,))
        tm.runner_loop(0)

    except KeyboardInterrupt:
        print("\n👋 User stop requested.")
    except Exception as e:
        print(f"❌ System Error: {e}")
    finally:
        # 🚀 統一機制替代 shutdown()
        bus.shared["engine_run"] = False
        print("🛑 All cores stopping...")
        time.sleep_ms(500) # 給 Core 1 一點時間收尾
        st_LED.big_buffer = bytearray(st_LED.total_bytes) 
        st_LED.show_all()
        print("🏁 Clean Exit.")

if __name__ == "__main__":
    launcher()

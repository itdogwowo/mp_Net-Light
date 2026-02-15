# main.py
import machine, time, _thread, ubinascii
from app import App
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub
import Core0_worker
import Core1_engine
from apa102 import APA102

def launcher():
    st_LED = bus.get_service("st_LED")
    
    # 總線與 ID
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True
    bus_sys = bus.shared["System"]
    
    # 🚀 註冊渲染用 Hub
    render_hub = AtomicStreamHub(st_LED.total_bytes * bus_sys["buffer_frames"])
    bus.register_service("pixel_stream", render_hub)
    
    try:
        # 🔥 啟動 CPU 1 任務
        _thread.start_new_thread(Core1_engine.task_loop, (st_LED, bus_sys["local_fps"]))
        
        print(f"✨ NetBus System Online: {bus.slave_id}")
        
        # 初始化 App 並註冊 store
        app = App()
        bus.register_service("schema_store", app.store)  # 🔥 註冊 store
        bus.register_service("app", app)  # 🔥 註冊 app
        
        # 🚀 啟動 CPU 0 主循環 (阻塞)
        Core0_worker.task_loop(app)
        
    except KeyboardInterrupt:
        print("\n👋 User stop requested.")
    except Exception as e:
        print(f"❌ System Error: {e}")
    finally:
        bus.shared["engine_run"] = False
        print("🛑 All cores stopping...")
        time.sleep_ms(500)
        st_LED.big_buffer = bytearray(st_LED.total_bytes)
        st_LED.show_all()
        print("🏁 Clean Exit.")

if __name__ == "__main__":
    launcher()
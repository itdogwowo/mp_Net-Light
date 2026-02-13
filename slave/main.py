# main.py
import machine, network, time, _thread, ubinascii
from app import App
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub
import Core0_worker
import Core1_engine
from apa102 import APA102


def launcher():
    st_LED = bus.get_service("st_LED")
    
    # 2. 總線與 ID
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True
    bus_sys = bus.shared["System"]
    # 3. 🚀 註冊核心交換服務 (不修改 lib，在此處申請)
    hub = AtomicStreamHub(st_LED.total_bytes * bus_sys["buffer_frames"]) 
    bus.register_service("pixel_stream", hub)

    
    
    
    

    try:

        # 4. 啟動雙核任務
        _thread.start_new_thread(Core1_engine.task_loop, (st_LED, bus_sys["local_fps"]))

        print(f"✨ NetBus System Online: {bus.slave_id}")
        
        app = App()
        # 🚀 啟動核心 0：Data 路由處理 (主線程阻塞)
        Core0_worker.task_loop(app)

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
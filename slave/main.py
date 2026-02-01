# main.py
import machine, network, time, _thread, ubinascii
from app import App
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub
import Core0_worker
import Core1_engine
from apa102 import APA102

CONFIG = {
    "refresh_rate_ms": 1,
    "discovery_port": 9000,
    "stream_port": 4050,
    "heartbeat_interval": 10000,
    "local_fps": 40,
    "num_leds": 336,
    "buffer_frames": 1,  # 幀緩衝區大小 (幀數)

}

def setup_network():
    # 確保 LAN 配置正確
    lan = network.LAN(mdc=31, mdio=52, phy_addr=1, phy_type=network.PHY_IP101, ref_clk=50)
    lan.active(True)
    for _ in range(20):
        if lan.isconnected():
            print(lan.ipconfig("addr4"))
            return True
        time.sleep(0.5)
    return False

def launcher():
    # 1. 硬件初始化 (假設 num_leds 由此獲取)
    NUM_LEDS = CONFIG["num_leds"]
    apa = APA102(num_leds=NUM_LEDS)
    
    # 2. 總線與 ID
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True
    bus.shared["num_leds"] = NUM_LEDS # 🚀 顯式存儲供後續使用

    # 3. 🚀 註冊核心交換服務 (不修改 lib，在此處申請)
    hub = AtomicStreamHub(NUM_LEDS * 4 * CONFIG["buffer_frames"]) 
    bus.register_service("pixel_stream", hub)

    
    
    
    

    try:

        # 4. 啟動雙核任務
        _thread.start_new_thread(Core1_engine.task_loop, (apa, 40))

        print(f"✨ NetBus System Online: {bus.slave_id}")
        
        app = App()
        # 🚀 啟動核心 0：Data 路由處理 (主線程阻塞)
        Core0_worker.task_loop(app, CONFIG)

    except KeyboardInterrupt:
        print("\n👋 User stop requested.")
    except Exception as e:
        print(f"❌ System Error: {e}")
    finally:
        # 🚀 統一機制替代 shutdown()
        bus.shared["engine_run"] = False
        print("🛑 All cores stopping...")
        time.sleep_ms(500) # 給 Core 1 一點時間收尾
        apa.clear()
        apa.show()
        print("🏁 Clean Exit.")

if __name__ == "__main__":
    setup_network()
    launcher()
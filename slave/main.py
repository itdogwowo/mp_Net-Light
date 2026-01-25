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
    "num_leds": 2000
}

def setup_network():
    # 確保 LAN 配置正確
    lan = network.LAN(mdc=31, mdio=52, phy_addr=1, phy_type=network.PHY_IP101, ref_clk=50)
    lan.active(True)
    for _ in range(20):
        if lan.isconnected(): return True
        time.sleep(0.5)
    return False

def launcher():
    if not setup_network():
        print("❌ Network Failed")
        return

    # 1. 核心硬件初始化 (APA102 @ 12MHz)
    apa = APA102(num_leds=CONFIG["num_leds"], sck_pin=22, mosi_pin=23, baudrate=12_000_000)
    
    # 2. 系統總線標識 (單例)
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True # 🚀 確保主開關開啟

    # 3. 建立並註冊交換服務 (8000 Bytes)
    hub = AtomicStreamHub(CONFIG["num_leds"] * 4) 
    bus.register_service("pixel_stream", hub)

    # 4. 裝配動作模組
    app = App(apa_driver=apa)

    try:
        # 🚀 啟動核心 1：專職渲染 (異步線程)
        _thread.start_new_thread(Core1_engine.task_loop, (apa, CONFIG["local_fps"]))

        print(f"✨ NetBus System Online: {bus.slave_id}")

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
    launcher()
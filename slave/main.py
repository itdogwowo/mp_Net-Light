"""
主入口文件
"""
import machine
import network
import time
import _thread
import ubinascii
from app import App
from lib.sys_bus import bus
from lib.buffer_hub import AtomicStreamHub
import Core0_worker
import Core1_engine
from apa102 import APA102

CONFIG = {
    "refresh_rate_ms": 1,
    "discovery_port": 9000,
    "heartbeat_interval": 10000,
    "local_fps": 40,
    "num_leds": 2000
}

def setup_network():
    """初始化 LAN"""
    lan = network.LAN(
        mdc=31,
        mdio=52,
        phy_addr=1,
        phy_type=network.PHY_IP101,
        ref_clk=50
    )
    lan.active(True)
    
    print("🔌 [Network] Waiting for LAN connection...")
    
    for _ in range(20):
        if lan.isconnected():
            ip_info = lan.ipconfig("addr4")
            print(f"✅ [Network] Connected: {ip_info}")
            return True
        time.sleep(0.5)
    
    print("❌ [Network] Connection Failed")
    return False

def launcher():
    """主啟動邏輯"""
    print("=" * 50)
    print("🚀 mp_Net-Light v3.0")
    print("=" * 50)
    
    NUM_LEDS = CONFIG["num_leds"]
    apa = APA102(num_leds=NUM_LEDS)
    print(f"✅ [Hardware] APA102 Driver: {NUM_LEDS} LEDs")
    
    bus.slave_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
    bus.shared["engine_run"] = True
    bus.shared["num_leds"] = NUM_LEDS
    
    print(f"🆔 [System] Slave ID: {bus.slave_id}")
    
    hub = AtomicStreamHub(NUM_LEDS * 4, num_buffers=3)
    bus.register_service("pixel_stream", hub)
    print(f"✅ [Service] AtomicStreamHub Registered")
    
    app = App()
    
    try:
        _thread.start_new_thread(Core1_engine.task_loop, (apa, CONFIG["local_fps"]))
        print(f"🔥 [Core 1] Rendering Engine Started @ {CONFIG['local_fps']} FPS")
        
        time.sleep(1)
        
        print(f"🚀 [Core 0] Network Engine Starting...")
        Core0_worker.task_loop(app, CONFIG)
    
    except KeyboardInterrupt:
        print("\n👋 User stop requested.")
    
    except Exception as e:
        print(f"❌ System Error: {e}")
        import sys
        sys.print_exception(e)
    
    finally:
        bus.shared["engine_run"] = False
        print("🛑 All cores stopping...")
        time.sleep_ms(500)
        
        apa.clear()
        apa.show()
        
        print("🏁 Clean Exit.")

if __name__ == "__main__":
    if setup_network():
        launcher()
    else:
        print("❌ [Main] Network setup failed, system not started")
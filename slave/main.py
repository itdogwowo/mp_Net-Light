import time

import gc

import network

import machine

from app import App

import time, gc, network, machine
from app import App
from lib.net_bus import NetBus
from apa102 import APA102
from action.stream_actions import is_streaming, get_mode, get_frame_count, reset_frame_count

CONFIG = {
    "refresh_rate_ms": 1,   
    "discovery_port": 9000,
    "stream_port": 4050,
    "heartbeat_interval": 10000,
    "local_fps_ms": 25, # 40 Hz
    "num_leds":2000
}

def setup_network():
    lan = network.LAN(mdc=31, mdio=52, phy_addr=1, phy_type=network.PHY_IP101, ref_clk=50)
    lan.active(True)
    for _ in range(20):
        if lan.isconnected(): return True
        time.sleep(0.5)
    return False

def main():
    if not setup_network(): return
    
    apa = APA102(num_leds=CONFIG['num_leds'], baudrate=12_000_000)
    app = App(apa_driver=apa)
    app.disp.debug_level = 0 # 🚀 強制關閉 Dispatch 打印，保證串流性能

    

    apa = APA102(num_leds=2000,sck_pin=22, mosi_pin=23)

    app = App(apa_driver=apa)

    app.disp.debug_level = 1 

    # 初始化總線

    ctrl_bus = NetBus(NetBus.TYPE_WS, app=app, label="CTRL-WS")
    discovery_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-DISCV")
    discovery_bus.connect(None, CONFIG["discovery_port"])
    stream_bus = NetBus(NetBus.TYPE_UDP, app=app, label="UDP-FAST")
    stream_bus.connect(None, CONFIG["stream_port"])

    # 🚀 將狀態函數緩存為本地變量，速度提升 5-10%

    check_streaming = is_streaming
    check_mode = get_mode
    file_rx = app.file_rx
    
    get_ticks = time.ticks_ms
    diff_ticks = time.ticks_diff
    
#     s = {
# 
#         "f_local": None,
#         "is_playing": False,
#         "last_hbeat": 0,
#         "last_frame_t": 0,
#         "has_next_frame": False,
#         "frame_count": 0,       # 🚀 新增：累積播放幀數
#         "last_report_t": 0      # 🚀 新增：上次報告時間
# 
#     }
    
    s = {
        "f_local": None,
        "is_playing": False,
        "next_frame_t": get_ticks(), # 🚀 改為預期目標時間
        "has_next_frame": False,
        "frame_count": 0,
        "last_report_t": get_ticks(),
        "last_hbeat": get_ticks()
    }

    def on_connect_request(url):
        if not ctrl_bus.connected:
            parts = url.replace("ws://", "").split("/", 1)

            host_port = parts[0]

            path = "/" + parts[1] if len(parts) > 1 else "/"

            host = host_port.split(":")[0]

            port = int(host_port.split(":")[1]) if ":" in host_port else 80

            ctrl_bus.connect(host, port, path=path)

    ctx_extra = {"on_connect": on_connect_request}

    

    # 初始化狀態字典
    print("🚀 [Core] 極速輪詢模式已啟動")

    # 🚀 為了性能，我們將 ticks_ms 緩存

    get_ticks = time.ticks_ms
    diff_ticks = time.ticks_diff

    

    

    s["last_report_t"] = get_ticks()

    try:

        while True:

            now = get_ticks()

            

            # --- 1. 網路優先級 (始終最高) ---

            discovery_bus.poll(**ctx_extra)

            if ctrl_bus.connected: ctrl_bus.poll()

            stream_bus.poll() 

            # --- 2. 播放邏輯 ---
            if check_streaming():
                if check_mode() == "local":
                    if not s["is_playing"]:
                        try:
                            s["f_local"] = open('data.bin', 'rb')
                            s["is_playing"] = True
                            s["next_frame_t"] = now # 初始化時鐘
                        except: s["is_playing"] = False
                    
                    # 預讀取：利用空閒 CPU 處理 IO
                    if s["is_playing"] and not s["has_next_frame"]:
                        if s["f_local"].readinto(apa.raw_buffer) == 0:
                            s["f_local"].seek(0)
                            s["f_local"].readinto(apa.raw_buffer)
                        s["has_next_frame"] = True

                    # 🚀 追趕補償判斷：只要目前時間 >= 理論目標時間，就 Show
                    if s["has_next_frame"]:
                        if diff_ticks(now, s["next_frame_t"]) >= 0:
                            apa.show() 
                            s["has_next_frame"] = False
                            s["frame_count"] += 1
                            # 更新下一幀目標時間 (不依賴 now，依賴理論步長)
                            s["next_frame_t"] += CONFIG["local_fps_ms"]
                else:
                    # Direct 模式清除文件句柄
                    if s["is_playing"]:
                        if s["f_local"]: s["f_local"].close()
                        s["f_local"] = None
                        s["is_playing"] = False
                    s["frame_count"] = get_frame_count()
            else:
                if s["is_playing"]:
                    if s["f_local"]: s["f_local"].close()
                    s["f_local"] = None
                    s["is_playing"] = False
                    apa.clear()
                    apa.show()

                    

                    

            if diff_ticks(now, s["last_hbeat"]) > CONFIG["heartbeat_interval"]:

                # 計算實際 FPS

                elapsed_ms = diff_ticks(now, s["last_report_t"])
                actual_fps = (s["frame_count"] * 1000) / elapsed_ms if elapsed_ms > 0 else 0

                # 只有在這一刻才產生打印 IO
                print(f"📊 FPS: {actual_fps:.2f} | RAM: {gc.mem_free()//1024}KB")
                
                s["last_hbeat"] = now
                s["last_report_t"] = now
                s["frame_count"] = 0
                if check_mode() != "local": reset_frame_count()
                gc.collect()

                mem = gc.mem_free() // 1024

                

                # 豪華日誌輸出面版

                print("-" * 40)

                print(f"📊 [Monitor] Actual FPS: {actual_fps:.2f} / {1000/CONFIG['local_fps_ms']:.0f}")

                print(f"💓 [System] RAM: {mem}KB | Frames: {s['frame_count']}")

                print("-" * 40)

                

                # 重置計數器進入下一個週期

                s["last_hbeat"] = now

                s["last_report_t"] = now

                s["frame_count"] = 0 

                if check_mode() != "local": # 同步重置 Direct 模式的計數器

                    from action.stream_actions import reset_frame_count

                    reset_frame_count()

            # 🚀 ESP32-P4 強大之處在於不需要長的 sleep，1ms 即可維持穩定

            time.sleep_ms(CONFIG["refresh_rate_ms"])

    except KeyboardInterrupt: pass

    finally:

        if s["f_local"]: s["f_local"].close()

        apa.deinit()

if __name__ == "__main__":

    main()
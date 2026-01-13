# /action/stream_actions.py
"""
燈效串流處理模組
處理 STREAM_START/FRAME/STOP 指令
"""
from lib.schema_loader import cmd_str_to_int
from lib.schema_codec import encode_payload
from lib.proto import pack_packet

# CMD 定義
CMD_STREAM_START = cmd_str_to_int("0x3002")
CMD_STREAM_FRAME = cmd_str_to_int("0x3001")
CMD_STREAM_STOP = cmd_str_to_int("0x3003")
CMD_STREAM_STATUS = cmd_str_to_int("0x3004")

# 全局狀態
STREAM_STATE = {
    "is_playing": False,
    "current_frame": 0,
    "dropped_frames": 0,
    "fps": 0,
    "pixel_count": 0,
    "led_strip": None  # LED 驅動實例
}

def on_stream_start(ctx, args):
    """處理 STREAM_START 指令"""
    global STREAM_STATE
    
    fps = args.get("fps", 40)
    pixel_count = args.get("pixel_count", 400)
    
    print("[Stream] STREAM_START: fps={}, pixels={}".format(fps, pixel_count))
    
    # 初始化 LED 驅動
    if STREAM_STATE["led_strip"] is None:
        try:
            from machine import Pin
            from neopixel import NeoPixel
            
            # 根據您的硬件配置修改引腳
            pin = Pin(13, Pin.OUT)  # 🔥 修改為實際引腳
            STREAM_STATE["led_strip"] = NeoPixel(pin, pixel_count)
            print("[Stream] LED 驅動已初始化")
        except Exception as e:
            print("[Stream] ❌ LED 初始化失敗: {}".format(e))
            return
    
    STREAM_STATE.update({
        "is_playing": True,
        "current_frame": 0,
        "dropped_frames": 0,
        "fps": fps,
        "pixel_count": pixel_count
    })
    
    print("[Stream] ✅ 串流已啟動")

def on_stream_frame(ctx, args):
    """處理 STREAM_FRAME 指令 (性能關鍵!)"""
    global STREAM_STATE
    
    if not STREAM_STATE["is_playing"]:
        return
    
    frame_id = args.get("frame_id", 0)
    pixel_data = args.get("pixel_data", b"")
    
    led_strip = STREAM_STATE.get("led_strip")
    if not led_strip:
        return
    
    # 快速路徑:直接寫入 LED buffer
    try:
        # pixel_data 格式: GRB GRB GRB... (每個像素 3 bytes)
        pixel_count = len(pixel_data) // 3
        
        for i in range(pixel_count):
            offset = i * 3
            g = pixel_data[offset]
            r = pixel_data[offset + 1]
            b = pixel_data[offset + 2]
            led_strip[i] = (r, g, b)
        
        # 立即更新顯示
        led_strip.write()
        
        STREAM_STATE["current_frame"] = frame_id
        
        # 性能優化:每 100 幀才打印一次
        if frame_id % 100 == 0:
            print("[Stream] Frame {} 已顯示".format(frame_id))
            
    except Exception as e:
        STREAM_STATE["dropped_frames"] += 1
        if STREAM_STATE["dropped_frames"] % 10 == 0:
            print("[Stream] ⚠️ 丟幀: {}".format(STREAM_STATE["dropped_frames"]))

def on_stream_stop(ctx, args):
    """處理 STREAM_STOP 指令"""
    global STREAM_STATE
    
    print("[Stream] STREAM_STOP")
    
    # 清空 LED
    led_strip = STREAM_STATE.get("led_strip")
    if led_strip:
        for i in range(STREAM_STATE.get("pixel_count", 0)):
            led_strip[i] = (0, 0, 0)
        led_strip.write()
    
    STREAM_STATE["is_playing"] = False
    
    print("[Stream] 📊 統計: 總幀數={}, 丟幀={}".format(
        STREAM_STATE["current_frame"],
        STREAM_STATE["dropped_frames"]
    ))

def register(app):
    """註冊 STREAM 指令"""
    app.disp.on(CMD_STREAM_START, on_stream_start)
    app.disp.on(CMD_STREAM_FRAME, on_stream_frame)
    app.disp.on(CMD_STREAM_STOP, on_stream_stop)
    
    print("[Stream] STREAM 指令已註冊")
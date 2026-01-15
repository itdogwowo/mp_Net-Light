# /action/stream_actions.py
"""
Stream 控制指令處理
- STREAM_START: 啟動串流接收
- STREAM_STOP: 停止串流
- STREAM_FRAME: 接收燈效幀數據
"""

# 全局 Stream 狀態
STREAM_STATE = {
    "active": False,
    "fps": 0,
    "pixel_count": 0,
    "frame_count": 0,
    "last_frame_id": 0
}

def register(app):
    """註冊 Stream 指令"""
    from lib.schema_loader import cmd_str_to_int
    
    CMD_STREAM_START = cmd_str_to_int("0x3001")
    CMD_STREAM_STOP = cmd_str_to_int("0x3002")
    CMD_STREAM_FRAME = cmd_str_to_int("0x3003")
    
    def on_stream_start(ctx, args):
        """處理 STREAM_START"""
        global STREAM_STATE
        
        fps = args.get("fps", 40)
        pixel_count = args.get("pixel_count", 400)
        
        STREAM_STATE["active"] = True
        STREAM_STATE["fps"] = fps
        STREAM_STATE["pixel_count"] = pixel_count
        STREAM_STATE["frame_count"] = 0
        STREAM_STATE["last_frame_id"] = 0
        
        print("[Stream] ✅ 啟動串流: fps={}, pixels={}".format(fps, pixel_count))
    
    def on_stream_stop(ctx, args):
        """處理 STREAM_STOP"""
        global STREAM_STATE
        
        total_frames = STREAM_STATE["frame_count"]
        STREAM_STATE["active"] = False
        
        print("[Stream] ⏹️ 停止串流 (總幀數: {})".format(total_frames))
    
    def on_stream_frame(ctx, args):
        """處理 STREAM_FRAME (接收燈效數據)"""
        global STREAM_STATE
        
        if not STREAM_STATE["active"]:
            return
        
        frame_id = args.get("frame_id", 0)
        pixel_data = args.get("pixel_data", b"")
        
        STREAM_STATE["frame_count"] += 1
        STREAM_STATE["last_frame_id"] = frame_id
        
        # TODO: 這裡應該驅動 LED 硬件
        # 例如: neopixel.write(pixel_data)
        
        # 每 100 幀打印一次
        if STREAM_STATE["frame_count"] % 100 == 0:
            print("[Stream] 📊 已接收 {} 幀".format(STREAM_STATE["frame_count"]))
    
    app.disp.on(CMD_STREAM_START, on_stream_start)
    app.disp.on(CMD_STREAM_STOP, on_stream_stop)
    app.disp.on(CMD_STREAM_FRAME, on_stream_frame)
    
    print("[Stream] STREAM 指令已註冊")

def is_streaming():
    """檢查當前是否在串流狀態"""
    return STREAM_STATE.get("active", False)

def get_stream_info():
    """獲取當前串流信息"""
    return STREAM_STATE.copy()
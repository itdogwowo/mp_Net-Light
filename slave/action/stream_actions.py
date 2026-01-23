# /action/stream_actions.py
import time

_STREAM_STATE = {
    "active": False,
    "mode": "local",
    "frame_id": 0,
    "fps": 40
}
_FRAME_COUNT = 0 

def is_streaming(): return _STREAM_STATE["active"]
def get_mode(): return _STREAM_STATE["mode"]
def get_frame_count(): return _FRAME_COUNT
def reset_frame_count():
    global _FRAME_COUNT
    _FRAME_COUNT = 0

def on_stream_start(ctx, args):
    """處理起始指令 (ws 或 udp 都適用)"""
    global _STREAM_STATE
    _STREAM_STATE["active"] = True
    _STREAM_STATE["fps"] = args.get("fps", 40)
    _STREAM_STATE["mode"] = args.get("mode", "local")
    _STREAM_STATE["frame_id"] = 0
    reset_frame_count()
    
    # 這裡不要裸寫 app
    print(f"🎬 [Stream] Start | Mode: {_STREAM_STATE['mode']} | FPS: {_STREAM_STATE['fps']}")

def on_stream_stop(ctx, args):
    """處理停止指令"""
    global _STREAM_STATE
    _STREAM_STATE["active"] = False
    print("⏹️ [Stream] Stopped")

def on_stream_frame(ctx, args):
    """雲端推流 (Direct Mode)"""
    global _FRAME_COUNT, _STREAM_STATE
    if not _STREAM_STATE["active"]: return
    
    _STREAM_STATE["mode"] = "direct"
    
    # 🚀 關鍵：從 ctx 安全獲取
    local_app = ctx.get("app")
    pixel_data = args.get("pixel_data")
    
    # 使用 local_app 替代 app
    if local_app and hasattr(local_app, "apa") and pixel_data:
        local_app.apa.raw_buffer[:len(pixel_data)] = pixel_data
        local_app.apa.show(is_rgbw=True)
        _FRAME_COUNT += 1
        _STREAM_STATE["frame_id"] = args.get("frame_id", 0)

def register(app):
    # 註冊時直接傳遞函數對象
    app.disp.on(0x3001, on_stream_start)
    app.disp.on(0x3002, on_stream_stop)
    app.disp.on(0x3003, on_stream_frame)
    print("✅ [Action] Stream actions cleaned")
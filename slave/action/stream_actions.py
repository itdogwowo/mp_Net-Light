# action/stream_actions.py
"""
LED Stream Actions - 業務邏輯層
═══════════════════════════════════════════════════════
職責:
- 管理 Block/Frame 等業務數據
- 協調 Hub 與協議指令
- 維護播放狀態
"""
import time
from lib.sys_bus import bus
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

# ══════════════════════════════════════════════════
# 常量定義
# ══════════════════════════════════════════════════

# 優先級
PRIORITY_QUEUE = 0       # 正常排隊
PRIORITY_IMMEDIATE = 1   # 立即跳轉
PRIORITY_PRELOAD = 2     # 預載入

# 狀態碼
STATUS_NOT_READY = 0
STATUS_READY = 1
STATUS_QUEUE_FULL = 2
STATUS_LOADING = 3

# ══════════════════════════════════════════════════
# 業務數據管理 (與 Hub 分離)
# ══════════════════════════════════════════════════

# 槽位 → 業務數據映射
_SLOT_META = {}

# 全局配置
_STREAM_STATE = {
    "total_blocks": 0,
    "f_per_block": 500,
    "fps": 40,
    "is_streaming": False,
    "is_paused": False,
}

# 當前播放狀態
_PLAYBACK = {
    "active_slot": None,
    "active_block": -1,
    "start_frame": 0,
    "local_frame": 0,
    "global_frame": 0,
    "block_start_time": 0,
    "render_count": 0
}

# ══════════════════════════════════════════════════
# 指令處理器
# ══════════════════════════════════════════════════

def on_stream_info(ctx, args):
    """0x3001: 接收地圖資訊"""
    _STREAM_STATE.update({
        "total_blocks": args["total_blocks"],
        "f_per_block": args["frames_per_block"],
        "fps": args["fps"]
    })
    print(f"📊 [Stream] {args['total_blocks']} Blocks × {args['frames_per_block']} Frames @ {args['fps']} FPS")


def on_stream_state_set(ctx, args):
    """
    0x3009: 設定播放目標
    ═══════════════════════════════════════════════════
    """
    hub = bus.get_service("pixel_stream")
    block_id = args["block_id"]
    frame_offset = args.get("frame_offset", 0)
    priority = args.get("priority", PRIORITY_QUEUE)
    
    # 驗證 frame_offset
    if frame_offset >= _STREAM_STATE["f_per_block"]:
        frame_offset = 0
    
    # 檢查 Block 是否已在緩衝區
    existing_slot = _find_slot_by_block_id(block_id)
    
    if existing_slot is not None:
        # 已存在
        status = hub.get_slot_status(existing_slot)
        
        if status == hub.READY:
            # 已就緒
            _send_ready_ack(ctx, block_id, frame_offset, STATUS_READY, existing_slot, -1)
            
            # 若是 IMMEDIATE,插隊
            if priority == PRIORITY_IMMEDIATE:
                hub.set_next(existing_slot)
                _SLOT_META[existing_slot]["frame_offset"] = frame_offset
                print(f"⚡ [Stream] IMMEDIATE JUMP to Slot {existing_slot} (Block {block_id}.{frame_offset})")
        
        elif status == hub.LOADING:
            # 正在載入
            _send_ready_ack(ctx, block_id, frame_offset, STATUS_LOADING, existing_slot, -1)
        
        return
    
    # 不存在,分配新槽位
    slot_idx, view = hub.get_write_view()
    
    if slot_idx is None:
        # 槽位已滿
        _send_ready_ack(ctx, block_id, frame_offset, STATUS_QUEUE_FULL, None, -1)
        return
    
    # 記錄業務數據 (在 Hub 外部)
    old_block = _SLOT_META.get(slot_idx, {}).get("block_id", -1)
    
    _SLOT_META[slot_idx] = {
        "block_id": block_id,
        "frame_offset": frame_offset,
        "loading": True
    }
    
    # 回報需要上傳
    _send_ready_ack(ctx, block_id, frame_offset, STATUS_NOT_READY, slot_idx, old_block)


def on_stream_play(ctx, args):
    """0x300A: 開始播放"""
    _STREAM_STATE["is_streaming"] = True
    _STREAM_STATE["is_paused"] = False
    
    _PLAYBACK["block_start_time"] = time.ticks_ms()
    _PLAYBACK["render_count"] = 0
    
    print("🚀 [Stream] PLAY")


def on_stream_pause(ctx, args):
    """0x3005: 暫停/恢復"""
    _STREAM_STATE["is_paused"] = bool(args["pause"])
    print(f"⏸️ [Stream] {'PAUSE' if args['pause'] else 'RESUME'}")


def on_stream_stop(ctx, args):
    """0x3002: 停止"""
    _STREAM_STATE["is_streaming"] = False
    _STREAM_STATE["is_paused"] = False
    
    _PLAYBACK["local_frame"] = 0
    _PLAYBACK["global_frame"] = 0
    _PLAYBACK["render_count"] = 0
    
    print("⏹️ [Stream] STOP")


def on_stream_seek(ctx, args):
    """0x3004: 跳轉 (等同於 IMMEDIATE 模式)"""
    on_stream_state_set(ctx, {
        "block_id": args["target_block"],
        "frame_offset": args["target_frame"],
        "priority": PRIORITY_IMMEDIATE,
        "target_slot": 0xFF
    })


# ══════════════════════════════════════════════════
# 文件接收完成處理
# ══════════════════════════════════════════════════

def on_file_complete(file_path):
    """
    檔案上傳完成回調
    ═══════════════════════════════════════════════════
    由 file_actions.py 調用
    """
    hub = bus.get_service("pixel_stream")
    
    # 提取 block_id
    block_id = _extract_block_id_from_path(file_path)
    if block_id == -1:
        return
    
    # 找到對應槽位
    slot_idx = _find_slot_by_block_id(block_id)
    
    if slot_idx is not None:
        # 提交 Hub
        hub.commit()
        
        # 更新業務數據
        _SLOT_META[slot_idx]["loading"] = False
        
        print(f"✅ [Stream] Block {block_id} → Slot {slot_idx} READY")


# ══════════════════════════════════════════════════
# Core 1 回調 (播放完成)
# ══════════════════════════════════════════════════

def on_block_complete(slot_idx):
    """
    Block 播完回調
    ═══════════════════════════════════════════════════
    由 Core1_engine.py 調用
    """
    meta = _SLOT_META.get(slot_idx, {})
    block_id = meta.get("block_id", -1)
    start_frame = _PLAYBACK["start_frame"]
    end_frame = _PLAYBACK["local_frame"] - 1
    
    # 計算實測 FPS
    play_time_ms = time.ticks_diff(time.ticks_ms(), _PLAYBACK["block_start_time"])
    render_count = _PLAYBACK["render_count"]
    actual_fps = (render_count * 1000.0) / play_time_ms if play_time_ms > 0 else 0
    
    # 發送 BLOCK_COMPLETE
    send_block_complete(
        block_id, start_frame, end_frame,
        play_time_ms, actual_fps, slot_idx, False
    )


# ══════════════════════════════════════════════════
# 輔助函數
# ══════════════════════════════════════════════════

def _find_slot_by_block_id(block_id):
    """根據 block_id 查找槽位索引"""
    for slot_idx, meta in _SLOT_META.items():
        if meta.get("block_id") == block_id:
            return slot_idx
    return None


def _extract_block_id_from_path(path):
    """從文件路徑提取 block_id"""
    try:
        # "data_5.bin" → 5
        return int(path.split("_")[1].split(".")[0])
    except:
        return -1


def _send_ready_ack(ctx, block_id, frame_offset, status, slot, replaced_block):
    """發送 READY_ACK"""
    app = ctx.get("app")
    if not app:
        return
    
    cmd_def = app.store.get(0x3008)
    if not cmd_def:
        return
    
    payload = SchemaCodec.encode(cmd_def, {
        "block_id": block_id,
        "frame_offset": frame_offset,
        "status": status,
        "slot": slot if slot is not None else 255,
        "replaced_block": replaced_block
    })
    
    send_func = ctx.get("send")
    if send_func:
        send_func(Proto.pack(0x3008, payload))
        
        status_str = ["NOT_READY", "READY", "QUEUE_FULL", "LOADING"][status]
        replace_info = f" (Replaced {replaced_block})" if replaced_block >= 0 else ""
        print(f"✅ [Stream] READY_ACK: Block {block_id}.{frame_offset} → {status_str} (Slot {slot}){replace_info}")


def send_block_complete(block_id, start_frame, end_frame, play_time_ms, actual_fps, freed_slot, interrupted):
    """發送 BLOCK_COMPLETE"""
    app = bus.shared.get("app")
    if not app:
        return
    
    cmd_def = app.store.get(0x3012)
    if not cmd_def:
        return
    
    next_block = _PLAYBACK.get("active_block", -1)
    next_frame = _PLAYBACK.get("local_frame", 0)
    
    payload = SchemaCodec.encode(cmd_def, {
        "block_id": block_id,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "play_time_ms": play_time_ms,
        "actual_fps": int(actual_fps * 100),
        "next_block": next_block,
        "next_frame": next_frame,
        "freed_slot": freed_slot,
        "interrupted": 1 if interrupted else 0
    })
    
    send_func = bus.shared.get("ws_send")
    if send_func:
        send_func(Proto.pack(0x3012, payload))
        
        status = "INTERRUPTED" if interrupted else "COMPLETE"
        print(f"📤 [Stream] BLOCK_{status}: {block_id} [{start_frame}~{end_frame}] → {actual_fps:.2f} FPS")


# ══════════════════════════════════════════════════
# 狀態回報 (Provider)
# ══════════════════════════════════════════════════

def get_mode():
    """回報當前模式"""
    if _STREAM_STATE["is_streaming"]:
        return "streaming"
    elif _STREAM_STATE["is_paused"]:
        return "paused"
    else:
        return "idle"


def get_frame_count():
    """回報當前幀計數"""
    return _PLAYBACK.get("local_frame", 0)


# ══════════════════════════════════════════════════
# 模組註冊
# ══════════════════════════════════════════════════

def register(app):
    """註冊 Stream 模組"""
    # 1. 確保 BufferHub 存在
    if not bus.get_service("pixel_stream"):
        num_leds = bus.shared.get("num_leds", 2000)
        f_per_block = _STREAM_STATE["f_per_block"]
        
        # 計算 Buffer 大小
        buffer_size = num_leds * f_per_block * 4
        
        from lib.buffer_hub import AtomicStreamHub
        hub = AtomicStreamHub(buffer_size, num_buffers=3)
        
        bus.register_service("pixel_stream", hub)
        print(f"🚀 [Stream] BufferHub: {buffer_size // 1024} KB × 3")
    
    # 2. 同步狀態到 bus.shared (供 Core 1 讀取)
    bus.shared["stream_state"] = _STREAM_STATE
    bus.shared["playback"] = _PLAYBACK
    bus.shared["slot_meta"] = _SLOT_META
    
    # 3. 註冊 Provider
    bus.register_provider("stream_mode", get_mode)
    bus.register_provider("stream_frame", get_frame_count)
    
    # 4. 註冊指令處理器
    app.disp.on(0x3001, on_stream_info)
    app.disp.on(0x3009, on_stream_state_set)
    app.disp.on(0x300A, on_stream_play)
    app.disp.on(0x3005, on_stream_pause)
    app.disp.on(0x3002, on_stream_stop)
    app.disp.on(0x3004, on_stream_seek)
    
    print("✅ [Action] Stream Engine Registered")
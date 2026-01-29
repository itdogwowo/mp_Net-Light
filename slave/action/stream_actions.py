"""
LED Stream Actions - 業務邏輯層
═══════════════════════════════════════════════════════
職責:
- 管理 Block 槽位映射 (Flash/RAM)
- 協調 Hub 與協議指令
- 維護播放狀態
- 定時回報與錯誤處理
"""
import time
import gc
import ujson
from lib.sys_bus import bus
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

# ══════════════════════════════════════════════════
# 常量定義
# ══════════════════════════════════════════════════

# 優先級
PRIORITY_QUEUE = 0
PRIORITY_IMMEDIATE = 1

# 狀態碼
STATUS_NOT_READY = 0
STATUS_READY = 1
STATUS_QUEUE_FULL = 2
STATUS_LOADING = 3

# 數據源類型
SOURCE_AUTO = 0
SOURCE_FLASH = 1
SOURCE_RAM = 2

# 錯誤碼
ERROR_FILE_NOT_FOUND = 1
ERROR_FILE_CORRUPTED = 2
ERROR_READ_FAILED = 3
ERROR_OOM = 4
ERROR_INVALID_CONFIG = 5
ERROR_SLOT_NOT_FOUND = 6

# ══════════════════════════════════════════════════
# 全局狀態
# ══════════════════════════════════════════════════

# 配置 (由 0x3001 初始化)
_CONFIG = {
    "initialized": False,
    "num_leds": 0,
    "f_per_block": 0,
    "total_blocks": 0,
    "fps": 40,
    "mode": 0,  # 0=Flash, 1=RAM, 2=混合
    "data_path": "/data/",
    "num_buffers": 3,
    "report_interval": 5000  # ms
}

# 槽位元數據
_SLOT_META = {}

# 播放狀態 (與 bus.shared 同步)
_PLAYBACK = {
    "is_streaming": False,
    "is_paused": False,
    "is_frozen": False,
    "active_slot": -1,
    "active_block": -1,
    "start_frame": 0,
    "local_frame": 0,
    "global_frame": 0,
    "block_start_time": 0,
    "render_count": 0,
    "last_report_time": 0
}

# 中斷標誌
_CONTROL = {
    "abort_now": False,
    "freeze_now": False
}

# ══════════════════════════════════════════════════
# 工具函數
# ══════════════════════════════════════════════════

def _get_file_path(block_id):
    """根據 block_id 計算文件路徑"""
    slot_file = block_id % _CONFIG["num_buffers"]
    return f"{_CONFIG['data_path']}{slot_file}.bin"

def _find_slot_by_block_id(block_id):
    """查找包含指定 block_id 的槽位"""
    for slot_idx, meta in _SLOT_META.items():
        if meta.get("block_id") == block_id:
            return slot_idx
    return None

def _get_slot_type(source):
    """
    決定槽位類型
    
    參數:
        source: 0=auto, 1=flash, 2=ram
    
    返回:
        "flash" 或 "ram"
    """
    if source == SOURCE_FLASH:
        return "flash"
    elif source == SOURCE_RAM:
        return "ram"
    else:  # AUTO
        mode = _CONFIG["mode"]
        if mode == 0:  # 純 Flash
            return "flash"
        elif mode == 1:  # 純 RAM
            return "ram"
        else:  # 混合 (根據記憶體)
            return "ram" if gc.mem_free() > 5*1024*1024 else "flash"

def _get_hub_status(slot_idx):
    """獲取 Hub 槽位狀態"""
    hub = bus.get_service("pixel_stream")
    if not hub:
        return None
    return hub.get_slot_status(slot_idx)

# ══════════════════════════════════════════════════
# 發送函數
# ══════════════════════════════════════════════════

def _send_ready_ack(ctx, block_id, frame_offset, status, slot, replaced_block, slot_type):
    """發送 READY_ACK"""
    app = ctx.get("app")
    if not app:
        return
    
    cmd_def = app.store.get(0x3008)
    if not cmd_def:
        return
    
    type_code = 1 if slot_type == "flash" else 2
    
    payload = SchemaCodec.encode(cmd_def, {
        "block_id": block_id,
        "frame_offset": frame_offset,
        "status": status,
        "slot": slot if slot is not None else 255,
        "replaced_block": replaced_block,
        "slot_type": type_code
    })
    
    send_func = ctx.get("send")
    if send_func:
        send_func(Proto.pack(0x3008, payload))
        
        status_str = ["NOT_READY", "READY", "QUEUE_FULL", "LOADING"][status]
        replace_info = f" (Replaced {replaced_block})" if replaced_block >= 0 else ""
        print(f"📤 [Stream] READY_ACK: Block {block_id}.{frame_offset} → {status_str} (Slot {slot}, {slot_type}){replace_info}")

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
        print(f"📤 [Stream] BLOCK_{status}: {block_id} [{start_frame}~{end_frame}] → {actual_fps:.2f} FPS (Freed Slot {freed_slot})")

def send_status_report():
    """發送狀態回報"""
    app = bus.shared.get("app")
    if not app:
        return
    
    cmd_def = app.store.get(0x3015)
    if not cmd_def:
        return
    
    # 收集槽位狀態
    hub = bus.get_service("pixel_stream")
    slots_info = []
    
    if hub:
        hub_status_map = {
            hub.IDLE: "IDLE",
            hub.LOADING: "LOADING",
            hub.READY: "READY",
            hub.PLAYING: "PLAYING"
        }
        
        for i in range(_CONFIG["num_buffers"]):
            meta = _SLOT_META.get(i, {})
            hub_status = hub.get_slot_status(i)
            
            slot_info = {
                "index": i,
                "status": hub_status_map.get(hub_status, "UNKNOWN"),
                "block_id": meta.get("block_id", -1),
                "type": meta.get("type", "unknown")
            }
            
            if meta.get("type") == "flash":
                slot_info["file_path"] = meta.get("file_path", "")
            
            slots_info.append(slot_info)
    
    # 計算實際 FPS
    play_time_ms = time.ticks_diff(time.ticks_ms(), _PLAYBACK["block_start_time"])
    render_count = _PLAYBACK["render_count"]
    actual_fps = (render_count * 1000.0) / play_time_ms if play_time_ms > 0 else 0.0
    
    # 組裝 JSON
    status_data = {
        "uptime_ms": time.ticks_ms(),
        "mem_free": gc.mem_free(),
        "actual_fps": round(actual_fps, 2),
        "current_block": _PLAYBACK["active_block"],
        "current_frame": _PLAYBACK["local_frame"],
        "slots": slots_info,
        "next_slot": hub._next_index if hub else -1
    }
    
    payload = SchemaCodec.encode(cmd_def, {
        "status_json": ujson.dumps(status_data)
    })
    
    send_func = bus.shared.get("ws_send")
    if send_func:
        send_func(Proto.pack(0x3015, payload))
        print(f"📊 [Stream] STATUS: FPS={actual_fps:.2f}, Block={_PLAYBACK['active_block']}, Frame={_PLAYBACK['local_frame']}")

def send_error(error_code, block_id, slot, message):
    """發送錯誤回報"""
    app = bus.shared.get("app")
    if not app:
        return
    
    cmd_def = app.store.get(0x3016)
    if not cmd_def:
        return
    
    payload = SchemaCodec.encode(cmd_def, {
        "error_code": error_code,
        "block_id": block_id,
        "slot": slot if slot is not None else 255,
        "message": message
    })
    
    send_func = bus.shared.get("ws_send")
    if send_func:
        send_func(Proto.pack(0x3016, payload))
        print(f"❌ [Stream] ERROR: Code={error_code}, Block={block_id}, Slot={slot}, Msg={message}")

# ══════════════════════════════════════════════════
# 指令處理器
# ══════════════════════════════════════════════════

def on_stream_config(ctx, args):
    """0x3001: 初始化配置"""
    # 更新配置
    _CONFIG.update({
        "initialized": True,
        "num_leds": args["num_leds"],
        "f_per_block": args["f_per_block"],
        "total_blocks": args["total_blocks"],
        "fps": args["fps"],
        "mode": args["mode"],
        "data_path": args["data_path"],
        "num_buffers": args["num_buffers"],
        "report_interval": args["report_interval"]
    })
    
    # 初始化 Hub
    hub = bus.get_service("pixel_stream")
    if hub:
        # 已存在,檢查是否需要重新分配
        mode = args["mode"]
        
        if mode == 0:  # 純 Flash
            # Flash 模式不需要大 Buffer
            print(f"🗂️ [Stream] Flash Mode (No Buffer Reallocation)")
        
        else:  # RAM 或混合模式
            # 需要大 Buffer,重新初始化
            required_size = args["num_leds"] * args["f_per_block"] * 4
            
            if hub.size < required_size:
                # Buffer 不夠大,重新分配
                print(f"🔄 [Stream] Reallocating Hub: {required_size // 1024} KB")
                
                from lib.buffer_hub import AtomicStreamHub
                hub = AtomicStreamHub(required_size, num_buffers=args["num_buffers"])
                bus.register_service("pixel_stream", hub)  # 覆寫舊的
            else:
                print(f"✅ [Stream] Existing Hub is sufficient")
    
    # 初始化槽位元數據
    _SLOT_META.clear()
    for i in range(args["num_buffers"]):
        _SLOT_META[i] = {
            "block_id": -1,
            "type": "unknown",
            "file_path": "",
            "fd": None,
            "frame_offset": 0,
            "frames": args["f_per_block"],
            "loading": False,
            "last_used": 0
        }
    
    # 同步到 bus.shared
    bus.shared["stream_config"] = _CONFIG
    bus.shared["stream_state"] = _PLAYBACK
    bus.shared["playback"] = _PLAYBACK
    bus.shared["slot_meta"] = _SLOT_META
    bus.shared["stream_control"] = _CONTROL
    bus.shared["num_leds"] = args["num_leds"]
    
    print(f"✅ [Stream] CONFIG: {args['num_leds']} LEDs, {args['f_per_block']} F/Block, {args['fps']} FPS, Mode={args['mode']}")

def on_stream_state_set(ctx, args):
    """0x3009: 設定播放目標"""
    if not _CONFIG["initialized"]:
        send_error(ERROR_INVALID_CONFIG, -1, None, "Not configured")
        return
    
    hub = bus.get_service("pixel_stream")
    if not hub:
        send_error(ERROR_INVALID_CONFIG, -1, None, "Hub not found")
        return
    
    block_id = args["block_id"]
    frame_offset = args.get("frame_offset", 0)
    priority = args.get("priority", PRIORITY_QUEUE)
    source = args.get("source", SOURCE_AUTO)
    
    # 驗證 frame_offset
    if frame_offset >= _CONFIG["f_per_block"]:
        frame_offset = 0
    
    # 決定槽位類型
    slot_type = _get_slot_type(source)
    
    if slot_type == "flash":
        file_path = _get_file_path(block_id)
    else:
        file_path = ""
    
    # 檢查 Block 是否已存在
    existing_slot = _find_slot_by_block_id(block_id)
    
    if existing_slot is not None:
        meta = _SLOT_META[existing_slot]
        
        if meta["type"] == slot_type:
            status = _get_hub_status(existing_slot)
            
            if status == hub.READY:
                _send_ready_ack(ctx, block_id, frame_offset, STATUS_READY, existing_slot, -1, slot_type)
                
                if priority == PRIORITY_IMMEDIATE:
                    hub.set_next(existing_slot)
                    _SLOT_META[existing_slot]["frame_offset"] = frame_offset
                    print(f"⚡ [Stream] IMMEDIATE JUMP to Slot {existing_slot}")
                
                return
            
            elif status == hub.LOADING:
                _send_ready_ack(ctx, block_id, frame_offset, STATUS_LOADING, existing_slot, -1, slot_type)
                return
    
    # Flash 模式: 檢查文件是否存在
    file_exists = False
    if slot_type == "flash":
        try:
            import os
            filename = file_path.split("/")[-1]
            files = os.listdir(_CONFIG["data_path"])
            file_exists = filename in files
        except:
            file_exists = False
    
    # 分配槽位
    if slot_type == "flash":
        # Flash: 固定映射
        target_slot = block_id % _CONFIG["num_buffers"]
        slot_status = _get_hub_status(target_slot)
        
        if slot_status in [hub.IDLE, hub.READY]:
            slot_idx = target_slot
        else:
            _send_ready_ack(ctx, block_id, frame_offset, STATUS_QUEUE_FULL, None, -1, slot_type)
            return
    else:
        # RAM: 找 IDLE
        slot_idx, _ = hub.get_write_view()
        
        if slot_idx is None:
            _send_ready_ack(ctx, block_id, frame_offset, STATUS_QUEUE_FULL, None, -1, slot_type)
            return
    
    # 更新元數據
    old_block = _SLOT_META[slot_idx].get("block_id", -1)
    
    old_fd = _SLOT_META[slot_idx].get("fd")
    if old_fd:
        try:
            old_fd.close()
        except:
            pass
    
    _SLOT_META[slot_idx].update({
        "block_id": block_id,
        "type": slot_type,
        "file_path": file_path,
        "fd": None,
        "frame_offset": frame_offset,
        "loading": not file_exists,
        "last_used": time.ticks_ms()
    })
    
    # 回應
    if slot_type == "flash" and file_exists:
        hub.commit()
        _send_ready_ack(ctx, block_id, frame_offset, STATUS_READY, slot_idx, old_block, slot_type)
        
        if priority == PRIORITY_IMMEDIATE:
            hub.set_next(slot_idx)
    else:
        _send_ready_ack(ctx, block_id, frame_offset, STATUS_NOT_READY, slot_idx, old_block, slot_type)

def on_stream_play(ctx, args):
    """0x300A: 開始播放"""
    _PLAYBACK["is_streaming"] = True
    _PLAYBACK["is_paused"] = False
    _PLAYBACK["is_frozen"] = False
    _PLAYBACK["block_start_time"] = time.ticks_ms()
    _PLAYBACK["render_count"] = 0
    _PLAYBACK["last_report_time"] = time.ticks_ms()
    
    bus.shared["is_streaming"] = True
    
    print("🚀 [Stream] PLAY")

def on_stream_pause(ctx, args):
    """0x3005: 暫停/恢復"""
    _PLAYBACK["is_paused"] = bool(args["pause"])
    print(f"⏸️ [Stream] {'PAUSE' if args['pause'] else 'RESUME'}")

def on_stream_stop(ctx, args):
    """0x3002: 停止"""
    _PLAYBACK["is_streaming"] = False
    _PLAYBACK["is_paused"] = False
    _PLAYBACK["is_frozen"] = False
    
    bus.shared["is_streaming"] = False
    
    print("⏹️ [Stream] STOP")

def on_stream_abort(ctx, args):
    """0x3010: 立即中斷"""
    _CONTROL["abort_now"] = True
    print("🛑 [Stream] ABORT")

def on_stream_freeze(ctx, args):
    """0x3011: 立即凍結"""
    _CONTROL["freeze_now"] = True
    _PLAYBACK["is_frozen"] = True
    print("❄️ [Stream] FREEZE")

def on_stream_status_get(ctx, args):
    """0x3014: 查詢狀態"""
    send_status_report()

# ══════════════════════════════════════════════════
# Core 1 回調
# ══════════════════════════════════════════════════

def on_block_complete(slot_idx, interrupted=False):
    """Block 播完回調"""
    meta = _SLOT_META.get(slot_idx, {})
    block_id = meta.get("block_id", -1)
    start_frame = _PLAYBACK["start_frame"]
    end_frame = _PLAYBACK["local_frame"] - 1
    
    play_time_ms = time.ticks_diff(time.ticks_ms(), _PLAYBACK["block_start_time"])
    render_count = _PLAYBACK["render_count"]
    actual_fps = (render_count * 1000.0) / play_time_ms if play_time_ms > 0 else 0.0
    
    fd = meta.get("fd")
    if fd:
        try:
            fd.close()
        except:
            pass
        _SLOT_META[slot_idx]["fd"] = None
    
    send_block_complete(
        block_id, start_frame, end_frame,
        play_time_ms, actual_fps, slot_idx, interrupted
    )

def check_auto_report():
    """檢查自動回報"""
    if not _PLAYBACK["is_streaming"]:
        return
    
    now = time.ticks_ms()
    interval = _CONFIG["report_interval"]
    
    if time.ticks_diff(now, _PLAYBACK["last_report_time"]) >= interval:
        send_status_report()
        _PLAYBACK["last_report_time"] = now

# ══════════════════════════════════════════════════
# Provider
# ══════════════════════════════════════════════════

def get_mode():
    if _PLAYBACK["is_frozen"]:
        return "frozen"
    elif _PLAYBACK["is_streaming"]:
        return "streaming"
    elif _PLAYBACK["is_paused"]:
        return "paused"
    else:
        return "idle"

def get_frame_count():
    return _PLAYBACK.get("local_frame", 0)

def get_actual_fps():
    play_time_ms = time.ticks_diff(time.ticks_ms(), _PLAYBACK["block_start_time"])
    render_count = _PLAYBACK["render_count"]
    return (render_count * 1000.0) / play_time_ms if play_time_ms > 0 else 0.0

# ══════════════════════════════════════════════════
# 模組註冊
# ══════════════════════════════════════════════════

def register(app):
    bus.register_provider("stream_mode", get_mode)
    bus.register_provider("stream_frame", get_frame_count)
    bus.register_provider("stream_fps", get_actual_fps)
    
    app.disp.on(0x3001, on_stream_config)
    app.disp.on(0x3009, on_stream_state_set)
    app.disp.on(0x300A, on_stream_play)
    app.disp.on(0x3005, on_stream_pause)
    app.disp.on(0x3002, on_stream_stop)
    app.disp.on(0x3010, on_stream_abort)
    app.disp.on(0x3011, on_stream_freeze)
    app.disp.on(0x3014, on_stream_status_get)
    
    print("✅ [Action] Stream Engine Registered")
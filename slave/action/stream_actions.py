# action/stream_actions.py
from lib.sys_bus import bus
from lib.proto import Proto
from lib.schema_codec import SchemaCodec

def on_stream_state_set(ctx, args):
    """0x3009: 準備狀態 (不播放)"""
    bus.shared.update({
        "active_file": args["file_name"],
        "cur_block": args["block_id"],
        "play_mode": args["play_mode"], # 0:Once, 1:Loop
        "is_seeking": True,             # 觸發 Core 0 打開文件
        "is_ready": False,
        "is_streaming": False           # 確保 Core 1 靜止
    })

def handle_supply_chain(hub, s, ctx):
    """由 Core0_worker 持續調用"""
    if bus.shared.get("is_seeking"):
        try:
            if s["f_local"]: s["f_local"].close()
            s["f_local"] = open(bus.shared["active_file"], "rb")
            # 填寫第一幀預熱
            view = hub.get_write_view()
            if s["f_local"].readinto(view) > 0:
                hub.commit()
            bus.shared["is_seeking"] = False
            bus.shared["is_ready"] = True
            
            # --- 🚀 自動向 PC 舉手回報 READY ---
            cmd_def = ctx["app"].store.get(0x3008)
            payload = SchemaCodec.encode(cmd_def, {"block_id": bus.shared["cur_block"]})
            ctx["send"](Proto.pack(0x3008, payload))
        except: bus.shared["is_seeking"] = False

    # 播放期間的預讀
    if bus.shared.get("is_streaming") and not bus.shared.get("is_paused"):
        # 利用 lib 自帶的 dirty 機制，這裡簡單判斷
        if not hub.dirty and s["f_local"]:
            view = hub.get_write_view()
            if s["f_local"].readinto(view) == 0:
                if bus.shared.get("play_mode") == 1: 
                    s["f_local"].seek(0)
                else: 
                    bus.shared["is_streaming"] = False # Stop
            else:
                hub.commit()

def register(app):
    # 播放控制
    app.disp.on(0x3009, on_stream_state_set) # SET
    app.disp.on(0x300A, lambda c,a: bus.shared.update({"is_streaming": True})) # PLAY
    app.disp.on(0x3005, lambda c,a: bus.shared.update({"is_paused": bool(a["pause"])})) # PAUSE
    app.disp.on(0x3002, lambda c,a: bus.shared.update({"is_streaming": False, "is_ready": False})) # STOP
    # 0x3003 Direct Mode
    app.disp.on(0x3003, lambda c,a: (bus.get_service("pixel_stream").get_write_view().__setitem__(slice(None), a["pixel_data"]), bus.get_service("pixel_stream").commit()))
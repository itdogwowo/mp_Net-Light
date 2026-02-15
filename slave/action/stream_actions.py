# action/stream_actions.py
from lib.sys_bus import bus
from lib.proto import Proto
from lib.schema_codec import SchemaCodec
from lib.sys_bus import bus
def on_stream_state_set(ctx, args):
    """0x3009: 準備分塊與文件模式"""
    bus.shared.update({
        "active_file": bus.get_service("data_Phat")+ '/' + args["file_name"],
        "cur_block": args["block_id"],
        "play_mode": args["play_mode"],
        "is_seeking": True,
        "is_ready": False,
        "is_streaming": False # 先設為 False 以免 Ready 途中亂跳
    })
    print(f"📡 [Stream] Set: {args['file_name']}")

def handle_supply_chain(hub, s, ctx):
    """由 Core 0 定時調用，負責加載與 READY 回報"""
    if bus.shared.get("is_seeking"):
        try:
            if s.get("f_local"): s["f_local"].close()
            s["f_local"] = open(bus.shared["active_file"], "rb")
            
            # 預填第一幀
            view = hub.get_write_view()
            if s["f_local"].readinto(view) > 0:
                hub.commit()
            
            bus.shared["is_seeking"] = False
            bus.shared["is_ready"] = True
            
            # --- 主動回報 READY 給 PC ---
            cmd_def = ctx["app"].store.get(0x3008)
            payload = SchemaCodec.encode(cmd_def, {"block_id": bus.shared["cur_block"]})
            ctx["send"](Proto.pack(0x3008, payload))
            print(f"✅ READY: {bus.shared['active_file']}")
        except Exception as e:
            print(f"❌ Load Error: {e}")
            bus.shared["is_seeking"] = False

    # 播放規律預讀
    if bus.shared.get("is_streaming") and not bus.shared.get("is_paused"):
        # 利用 Hub 自帶 dirty 位檢查供給
        if not hub.dirty and s.get("f_local"):
            view = hub.get_write_view()
            if s["f_local"].readinto(view) == 0:
                if bus.shared.get("play_mode") == 1: s["f_local"].seek(0)
                else: bus.shared["is_streaming"] = False
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
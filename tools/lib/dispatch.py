import time

class Dispatcher:
    # 調試等級：0: 關閉, 1: 僅指令, 2: 完整 Payload
    debug_level = 1 

    def __init__(self, store):
        self.store = store
        self.handlers = {}

    def on(self, cmd_int, handler):
        self.handlers[cmd_int] = handler

    def dispatch(self, cmd_int, payload_bytes, ctx):
        cmd_def = self.store.get(cmd_int)
        
        # 1. 基礎診斷
        if not cmd_def:
            if self.debug_level > 0:
                print(f"❓ [Unknown] 0x{cmd_int:04X} | Len: {len(payload_bytes)}")
            return

        handler = self.handlers.get(cmd_int)
        if not handler:
            if self.debug_level > 0:
                print(f"⚠️  [No-Handler] {cmd_def['name']} (0x{cmd_int:04X})")
            return

        # 2. 解析數據
        try:
            from lib.schema_codec import SchemaCodec
            args = SchemaCodec.decode(cmd_def, payload_bytes)
            
            # 3. 調試輸出面板 (現代化風格)
            if self.debug_level >= 1:
                t = time.ticks_ms()
                source = ctx.get("transport", "Unknown")
                print(f"🔹 [{source}] {cmd_def['name']} (0x{cmd_int:04X})")
                if self.debug_level >= 2:
                    print(f"   ﹂ Args: {args}")

            # 4. 執行與性能監控
            start_t = time.ticks_us()
            handler(ctx, args)
            end_t = time.ticks_us()
            
            if self.debug_level >= 2:
                print(f"   ﹂ ✅ Exec Time: {end_t - start_t} us")

        except Exception as e:
            print(f"❌ [Error] {cmd_def['name']}: {e}")
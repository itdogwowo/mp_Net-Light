import time
import struct

from lib.sys_bus import bus

QUIET_CMDS = {0x1812}

def dprint(msg, level=1):
    """
    統一的簡短日誌入口 (Dispatcher.log 的別名)
    Usage: dprint("Hello")
    """
    if Dispatcher.debug_level >= level:
        print(msg)

class Dispatcher:
    # 調試等級：0: 關閉, 1: 僅指令, 2: 完整 Payload
    debug_level = 1 

    @staticmethod
    def log(msg, level=1):
        """統一的日誌入口，取代 debugPrint"""
        if Dispatcher.debug_level >= level:
            print(msg)

    def __init__(self, store):
        self.store = store
        self.handlers = {}
        self._fast_args = {}

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
            args = None
            if cmd_int == 0x1812:
                a = self._fast_args.get(0x1812)
                if a is None:
                    a = {}
                    self._fast_args[0x1812] = a
                if len(payload_bytes) >= 6:
                    a["run_id"] = struct.unpack_from("<H", payload_bytes, 0)[0]
                    a["seq"] = struct.unpack_from("<I", payload_bytes, 2)[0]
                    a["data"] = memoryview(payload_bytes)[6:]
                else:
                    a["run_id"] = 0
                    a["seq"] = 0
                    a["data"] = memoryview(payload_bytes)[0:0]
                args = a
            else:
                from lib.schema_codec import SchemaCodec
                args = SchemaCodec.decode(cmd_def, payload_bytes)
            
            # 3. 調試輸出面板 (現代化風格)
            if self.debug_level >= 1 and cmd_int not in QUIET_CMDS:
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

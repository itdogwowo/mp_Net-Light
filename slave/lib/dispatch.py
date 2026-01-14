# /lib/dispatch.py (修改 dispatch 方法)

class Dispatcher:
    def __init__(self, schema_store):
        self.schema = schema_store
        self.handlers = {}
    
    def on(self, cmd_int, handler):
        self.handlers[cmd_int] = handler
    
    def dispatch(self, cmd_int, payload_bytes, ctx):
        """
        解碼 payload 並執行 handler
        🔥 新增: 打印正在執行的 CMD
        """
        handler = self.handlers.get(cmd_int)
        if not handler:
            print("[Dispatch] ⚠️ 未註冊 cmd=0x{:04X}".format(cmd_int))
            return
        
        cmd_def = self.schema.get(cmd_int)
        if not cmd_def:
            print("[Dispatch] ⚠️ schema 未找到 cmd=0x{:04X}".format(cmd_int))
            return
        
        from lib.schema_codec import decode_payload
        args = decode_payload(cmd_def, payload_bytes)
        
        # 🔥 新增:打印正在執行的 CMD
        cmd_name = cmd_def.get("name", "UNKNOWN")
        print("[Dispatch] 🔥 執行 CMD: 0x{:04X} ({})".format(cmd_int, cmd_name))
        print("[Dispatch]    參數: {}".format(args))
        
        # 執行 handler
        try:
            handler(ctx, args)
            print("[Dispatch] ✅ CMD 執行完成: {}".format(cmd_name))
        except Exception as e:
            print("[Dispatch] ❌ CMD 執行失敗: {}".format(e))
            import sys
            sys.print_exception(e)
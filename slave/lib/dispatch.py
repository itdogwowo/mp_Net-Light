# /lib/dispatch.py
from lib.schema_codec import decode_payload

class Dispatcher:
    def __init__(self, schema_store):
        self.schema_store = schema_store
        self.handlers = {}  # cmd_int -> fn(ctx, args)

    def on(self, cmd_int: int, fn):
        self.handlers[cmd_int] = fn

    def dispatch(self, cmd_int: int, payload: bytes, ctx: dict):
        cmd_def = self.schema_store.get(cmd_int)
        if not cmd_def:
            print("未知 CMD: 0x%04X（schema 未載入）" % cmd_int)
            return

        args = decode_payload(cmd_def, payload)
        fn = self.handlers.get(cmd_int)
        if not fn:
            print("未處理 CMD: 0x%04X name=%s" % (cmd_int, cmd_def.get("name")))
            return

        fn(ctx, args)
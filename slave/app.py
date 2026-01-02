# app.py
# 裝配層：載入 schema、建立 dispatcher、載入 /action 註冊 cmd handlers
# 經常改動的註冊行為會在 /action 內，不讓 /lib 變亂

from lib.proto import StreamParser
from lib.schema_loader import SchemaStore
from lib.dispatch import Dispatcher
from lib.file_rx import FileRx

from action.registry import register_all


class App:
    def __init__(self, schema_dir="/schema"):
        self.store = SchemaStore()
        self.store.load_dir(schema_dir)

        self.disp = Dispatcher(self.store)
        self.parser = StreamParser(max_len=4096, accept_addr=None)

        # shared modules (action handlers 會用到)
        self.file_rx = FileRx()

        # register all actions
        register_all(self)

    def on_rx_bytes(self, data: bytes, ctx=None):
        """
        任意總線餵入 bytes（TCP/UART/檔案/loopback）
        """
        if ctx is None:
            ctx = {}
        self.parser.feed(data)
        for ver, addr, cmd, payload in self.parser.pop():
            self.disp.dispatch(cmd, payload, ctx)
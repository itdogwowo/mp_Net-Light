import time
from lib.task import Task
from lib.sys_bus import bus
from action.stream_actions import handle_supply_chain
from action.heartbeat_actions import send_heartbeat
from action.status_actions import on_status_get
from lib.buffer_hub import AtomicStreamHub


class NetworkDecodeTask(Task):
    def __init__(self, name, ctx):
        super().__init__(name, ctx)
        self.app = ctx["app"]
        self.parser = None

        self.rx_hub = None
        self.tx_hub = None
        self.pixel_hub = None

        self.s = {"f_local": None, "last_hb": time.ticks_ms()}

    def on_start(self):
        super().on_start()

        base_size = bus.shared.get("Buffer", {}).get("size", 4096)
        rx_slot = base_size + 3
        tx_slot = base_size + 2

        self.rx_hub = bus.get_service("net_rx")
        if not self.rx_hub:
            self.rx_hub = AtomicStreamHub(rx_slot, num_buffers=4)
            bus.register_service("net_rx", self.rx_hub)

        self.tx_hub = bus.get_service("net_tx")
        if not self.tx_hub:
            self.tx_hub = AtomicStreamHub(tx_slot, num_buffers=8)
            bus.register_service("net_tx", self.tx_hub)

        self.pixel_hub = bus.get_service("pixel_stream")
        self.parser = self.app.create_parser(max_len=65535)

        print("🚀 [NetworkDecode] Online")

    def _send_enqueue(self, data):
        if not self.tx_hub or not data:
            return False

        mv = data if isinstance(data, memoryview) else memoryview(data)
        n = len(mv)
        pos = 0

        view0 = self.tx_hub.get_write_view()
        if view0 is None:
            return False
        max_payload = len(view0) - 2

        while pos < n:
            view = self.tx_hub.get_write_view()
            if view is None:
                return False
            take = n - pos
            if take > max_payload:
                take = max_payload
            view[0] = take & 0xFF
            view[1] = (take >> 8) & 0xFF
            view[2 : 2 + take] = mv[pos : pos + take]
            self.tx_hub.commit()
            pos += take

        return True

    def _drain_rx(self):
        if not self.rx_hub or not self.parser:
            return

        while True:
            view = self.rx_hub.get_read_view()
            if view is None:
                return
            chan = int(view[0])
            ln = int(view[1]) | (int(view[2]) << 8)
            if ln:
                transport = "CTRL-WS" if chan == 0 else "UDP-DISCV"
                ctx_extra = {"on_connect": self._request_connect}
                self.app.handle_stream(
                    self.parser,
                    view[3 : 3 + ln],
                    transport_name=transport,
                    send_func=self._send_enqueue,
                    **ctx_extra,
                )

    def _request_connect(self, url):
        bus.shared["net_connect_url"] = url

    def loop(self):
        if not self.running:
            return

        self._drain_rx()

        worker_ctx = {"app": self.app, "send": self._send_enqueue}
        if self.pixel_hub:
            handle_supply_chain(self.pixel_hub, self.s, worker_ctx)

        bus_sys = bus.shared["System"]
        now = time.ticks_ms()
        if time.ticks_diff(now, self.s["last_hb"]) > bus_sys["heartbeat_interval"]:
            if bus.shared.get("is_streaming") and bus.shared.get("app_connected"):
                send_heartbeat(worker_ctx)
                on_status_get(worker_ctx, {"query_type": 1})
            self.s["last_hb"] = now

    def on_stop(self):
        super().on_stop()
        print("NetworkDecode Stopped")

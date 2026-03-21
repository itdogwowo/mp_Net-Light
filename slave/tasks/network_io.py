import time
from lib.task import Task
from lib.sys_bus import bus
from lib.net_bus import NetBus
from action.sys_actions import on_connect_request
from lib.network_manager import NetworkManager
from lib.fs_manager import fs
from lib.buffer_hub import AtomicStreamHub


class NetworkIOTask(Task):
    def __init__(self, name, ctx):
        super().__init__(name, ctx)
        self.app = ctx["app"]
        self.nm = None
        self.ctrl_bus = None
        self.discovery_bus = None
        self.tried_config_connect = False

        self.rx_hub = None
        self.tx_hub = None

        self._pending = None
        self._pending_pos = 0
        self._pending_chan = 0

    def on_start(self):
        super().on_start()

        self.nm = bus.get_service("network_manager")
        if not self.nm:
            self.nm = NetworkManager(bus)
            self.nm.init_from_config()

        bus_sys = bus.shared["System"]

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

        self.ctrl_bus = NetBus(NetBus.TYPE_WS, label="CTRL-WS", buf_size=65535)
        self.discovery_bus = NetBus(NetBus.TYPE_UDP, label="UDP-DISCV")
        self.discovery_bus.connect(None, bus_sys["discovery_port"])

        print("🚀 [NetworkIO] Online")

    def _on_connect_wrapper(self, url):
        return on_connect_request(self.ctrl_bus, url)

    def _drain_tx(self):
        if not self.tx_hub or not self.ctrl_bus or not self.ctrl_bus.connected:
            return

        while True:
            view = self.tx_hub.get_read_view()
            if view is None:
                return
            ln = int(view[0]) | (int(view[1]) << 8)
            if ln:
                self.ctrl_bus.write(view[2 : 2 + ln])

    def _try_push_rx(self, chan, data):
        if not data:
            return True
        if not self.rx_hub:
            return False

        max_payload = len(self.rx_hub.get_write_view() or b"") - 3
        if max_payload <= 0:
            return False

        mv = data if isinstance(data, memoryview) else memoryview(data)
        n = len(mv)

        while self._pending_pos < n:
            view = self.rx_hub.get_write_view()
            if view is None:
                return False
            take = n - self._pending_pos
            if take > max_payload:
                take = max_payload
            view[0] = chan & 0xFF
            view[1] = take & 0xFF
            view[2] = (take >> 8) & 0xFF
            view[3 : 3 + take] = mv[self._pending_pos : self._pending_pos + take]
            self.rx_hub.commit()
            self._pending_pos += take

        return True

    def loop(self):
        if not self.running:
            return

        if bus.shared.get("fs_scan_done"):
            fs.finalize_scan()

        bus.shared["app_connected"] = self.ctrl_bus.connected or bus.shared.get("manual_keep_alive", False)

        network_ok = self.nm.check_network()
        if network_ok:
            bus_sys = bus.shared["System"]
            if not self.tried_config_connect and not self.ctrl_bus.connected:
                self.tried_config_connect = True
                m_ip = bus_sys.get("master_IP", "")
                m_port = bus_sys.get("master_port", 0)
                if m_ip and m_port:
                    full_url = f"ws://{m_ip}:{m_port}/ws/{bus.slave_id}"
                    self._on_connect_wrapper(full_url)
            self.discovery_bus.poll()
            d = self.discovery_bus.get_view()
            if d is not None:
                self._pending = d
                self._pending_pos = 0
                self._pending_chan = 1
                if self._try_push_rx(self._pending_chan, self._pending):
                    self._pending = None
                    self._pending_pos = 0

        self._drain_tx()

        if self._pending is not None:
            if self._try_push_rx(self._pending_chan, self._pending):
                self._pending = None
                self._pending_pos = 0
            return

        if self.ctrl_bus and self.ctrl_bus.connected:
            self.ctrl_bus.poll()
            data = self.ctrl_bus.get_view()
            if data is not None:
                self._pending = data
                self._pending_pos = 0
                self._pending_chan = 0
                if self._try_push_rx(self._pending_chan, self._pending):
                    self._pending = None
                    self._pending_pos = 0

        url = bus.shared.get("net_connect_url")
        if url:
            bus.shared["net_connect_url"] = ""
            if not self.ctrl_bus.connected:
                self._on_connect_wrapper(url)

        time.sleep_ms(0)

    def on_stop(self):
        super().on_stop()
        if self.ctrl_bus:
            self.ctrl_bus.disconnect()
        print("NetworkIO Stopped")

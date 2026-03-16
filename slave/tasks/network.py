import time

from lib.task import Task
from lib.sys_bus import bus
from lib.net_bus import NetBus
from lib.network_manager import NetworkManager
from lib.fs_manager import fs

from action.sys_actions import on_connect_request


class NetworkTask(Task):
    def on_start(self):
        super().on_start()
        bus.shared["core0_ready"] = True
        self._app = self.ctx["app"]
        self._bus_sys = self.ctx.get("bus_sys", {})
        self._nm = bus.get_service("network_manager")
        if not self._nm:
            self._nm = NetworkManager(bus)
            self._nm.init_from_config()
        self._discovery_bus = NetBus(NetBus.TYPE_UDP, app=self._app, label="UDP-DISCV")
        self._discovery_bus.connect(None, self._bus_sys["discovery_port"])
        self._ctrl_bus = NetBus(NetBus.TYPE_WS, app=self._app, label="CTRL-WS")
        self._ctx_extra_pre = {"app": self._app, "ctrl_bus": None}
        self._ctx_extra = {"app": self._app, "ctrl_bus": self._ctrl_bus, "on_connect": self._on_connect_wrapper}
        self._tried_config_connect = False
        self._state = "wait_core1"
        self._boot_start_ms = time.ticks_ms()
        self._last_log_ms = self._boot_start_ms
        self._scan_timeout_s = int(self._bus_sys.get("fs_scan_timeout_s", 0) or 0)
        self._force_scan = bool(self._bus_sys.get("fs_force_scan_on_boot", False))
        if self._force_scan and not bus.shared.get("fs_scan_requested"):
            bus.shared["fs_scan_requested"] = True
        self._need_scan = bool(bus.shared.get("fs_scan_requested"))
        bus.shared["system_online"] = False

    def _on_connect_wrapper(self, url):
        return on_connect_request(self._ctrl_bus, url)

    def _poll_discovery(self):
        self._discovery_bus.poll(**self._ctx_extra_pre)

    def _boot_gate(self):
        if not bus.shared.get("core1_ready"):
            self._poll_discovery()
            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_log_ms) > 1000:
                print("⏳ [BOOT] Waiting Core 1 ready...")
                self._last_log_ms = now
            return False

        if not self._need_scan:
            return True

        self._poll_discovery()

        if bus.shared.get("fs_scan_done"):
            fs.finalize_scan()
            self._need_scan = False
            return True

        now = time.ticks_ms()
        if self._scan_timeout_s > 0 and time.ticks_diff(now, self._boot_start_ms) > self._scan_timeout_s * 1000:
            print("❌ [BOOT] FS scan timeout, continue without manifest refresh")
            self._need_scan = False
            return True

        if time.ticks_diff(now, self._last_log_ms) > 1000:
            p = bus.shared.get("fs_scan_progress") or {}
            done = int(p.get("done") or 0)
            total = int(p.get("total") or 0)
            if total > 0:
                pct = int((done * 100) // total)
                print(f"⏳ [BOOT] FS scan running... ({done}/{total}, {pct}%)")
            else:
                print(f"⏳ [BOOT] FS scan running... ({done})")
            self._last_log_ms = now
        return False

    def _enter_online(self):
        bus.shared["system_online"] = True
        print(f"✨ NetBus System Online: {bus.slave_id}")
        pending_url = bus.shared.get("pending_connect_url")
        if pending_url and not self._ctrl_bus.connected:
            try:
                if on_connect_request(self._ctrl_bus, pending_url):
                    print("✅ Auto-Connect Success (deferred)!")
            except Exception as e:
                print(f"⚠️ Deferred connect error: {e}")
            bus.shared["pending_connect_url"] = None

    def loop(self):
        if bus.shared.get("fs_scan_done"):
            fs.finalize_scan()
            self._need_scan = False

        if self._state != "online":
            if self._boot_gate():
                self._enter_online()
                self._state = "online"
            else:
                return

        bus.shared["app_connected"] = self._ctrl_bus.connected or bool(bus.shared.get("manual_keep_alive", False))

        network_ok = self._nm.check_network()
        if network_ok:
            if (not self._tried_config_connect) and (not self._ctrl_bus.connected):
                self._tried_config_connect = True
                m_ip = self._bus_sys.get("master_IP", "")
                m_port = self._bus_sys.get("master_port", 0)
                if m_ip and m_port:
                    print(f"🔄 Auto-Connecting to stored Master: {m_ip}:{m_port}")
                    full_url = f"ws://{m_ip}:{m_port}/ws/{bus.slave_id}"
                    if self._on_connect_wrapper(full_url):
                        print("✅ Auto-Connect Success!")
                    else:
                        print("⚠️ Auto-Connect Failed, waiting for discovery...")

            try:
                self._discovery_bus.poll(**self._ctx_extra)
                if self._ctrl_bus.connected:
                    self._ctrl_bus.poll()
            except Exception as e:
                print(f"📡 Network Poll Error: {e}")

    def on_stop(self):
        try:
            if self._ctrl_bus:
                self._ctrl_bus.disconnect()
        except Exception:
            pass
        super().on_stop()

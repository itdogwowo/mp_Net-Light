import time

from lib.task import Task
from lib.sys_bus import bus

from action.stream_actions import handle_supply_chain


class SupplyChainTask(Task):
    def on_start(self):
        super().on_start()
        self._app = self.ctx["app"]
        self._hub = bus.get_service("pixel_stream")
        self._state = {"f_local": None, "last_hb": time.ticks_ms()}
        self._interval_ms = int(self.ctx.get("bus_sys", {}).get("refresh_rate_ms", 1) or 1)
        if self._interval_ms < 0:
            self._interval_ms = 0
        self._next_ms = time.ticks_ms()
        self._noop_send = lambda b: None

    def loop(self):
        if not bus.shared.get("system_online"):
            return
        now = time.ticks_ms()
        if self._interval_ms and time.ticks_diff(now, self._next_ms) < 0:
            return
        self._next_ms = time.ticks_add(now, self._interval_ms)
        if not self._hub:
            self._hub = bus.get_service("pixel_stream")
            if not self._hub:
                return
        worker_ctx = {"app": self._app, "send": (self.ctx.get("send") or self._noop_send)}
        tm = bus.get_service("task_manager")
        if tm:
            net = tm.get_task("network")
            if net and getattr(net, "_ctrl_bus", None):
                worker_ctx["send"] = net._ctrl_bus.write
        handle_supply_chain(self._hub, self._state, worker_ctx)

    def on_stop(self):
        try:
            f = self._state.get("f_local")
            if f:
                f.close()
        except Exception:
            pass
        super().on_stop()


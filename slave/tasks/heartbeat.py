import time
import gc

from lib.task import Task
from lib.sys_bus import bus

from action.heartbeat_actions import send_heartbeat
from action.status_actions import on_status_get


class HeartbeatTask(Task):
    def on_start(self):
        super().on_start()
        self._app = self.ctx["app"]
        self._bus_sys = self.ctx.get("bus_sys", {})
        self._interval_ms = int(self._bus_sys.get("heartbeat_interval", 1000) or 1000)
        self._next_ms = time.ticks_ms()

    def loop(self):
        if not bus.shared.get("system_online"):
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._next_ms) < 0:
            return
        self._next_ms = time.ticks_add(now, self._interval_ms)
        tm = bus.get_service("task_manager")
        ctrl_send = None
        ctrl_connected = False
        if tm:
            net = tm.get_task("network")
            if net and getattr(net, "_ctrl_bus", None):
                ctrl_send = net._ctrl_bus.write
                ctrl_connected = bool(net._ctrl_bus.connected)
        if bus.shared.get("is_streaming") and ctrl_send and ctrl_connected:
            send_heartbeat({"app": self._app, "send": ctrl_send, "is_ws": True})
            on_status_get({"app": self._app, "send": ctrl_send}, {"query_type": 1})
        gc.collect()


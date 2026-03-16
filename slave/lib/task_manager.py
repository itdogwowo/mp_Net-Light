import time
from lib.sys_bus import bus


class TaskManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self._task_classes = {}
        self._tasks = {}
        self._aff = {}
        self._run_once = {}
        self._active = {0: {}, 1: {}}
        self._owner = {}
        self._error_until_ms = {0: {}, 1: {}}
        self._boot_error_until_ms = {0: {}, 1: {}}
        bus.register_service("task_manager", self)
        bus.shared.setdefault("core0_boot_done", False)
        bus.shared.setdefault("core1_boot_done", False)
        bus.shared.setdefault("boot_done", False)

    def register_task(self, name, task_cls, affinity=(0, 0), run_once=False):
        self._task_classes[name] = task_cls
        self._aff[name] = affinity
        self._run_once[name] = bool(run_once)
        if name not in self._owner:
            self._owner[name] = None
        self._ensure_atomic_stream_hub()

    def _ensure_atomic_stream_hub(self):
        if bus.get_service("pixel_stream") is not None:
            return
        st = self.ctx.get("st_LED")
        bus_sys = self.ctx.get("bus_sys") or {}
        frames = bus_sys.get("buffer_frames")
        if not st or not frames:
            return
        try:
            frames = int(frames)
        except Exception:
            return
        if frames <= 0:
            return
        from lib.buffer_hub import AtomicStreamHub
        hub = AtomicStreamHub(st.total_bytes * frames)
        bus.register_service("pixel_stream", hub)

    def _ensure_task_instance(self, name):
        t = self._tasks.get(name)
        if t is not None:
            return t
        cls = self._task_classes.get(name)
        if not cls:
            return None
        t = cls(name, self.ctx)
        t.run_once = self._run_once.get(name, False)
        self._tasks[name] = t
        return t

    def set_affinity(self, name, affinity):
        if affinity == (1, 1):
            return False
        self._aff[name] = affinity
        return True

    def get_affinity(self, name):
        return self._aff.get(name, (0, 0))

    def get_task(self, name):
        return self._tasks.get(name)

    def _start_task(self, core_id, name):
        if self._owner.get(name) not in (None, core_id):
            return
        t = self._ensure_task_instance(name)
        if not t:
            return
        self._owner[name] = core_id
        try:
            t.on_start()
        except Exception as e:
            self._owner[name] = None
            bus.shared.setdefault("task_errors", {})[f"start:{name}"] = str(e)
            return
        self._active[core_id][name] = t

    def _stop_task(self, core_id, name):
        t = self._active[core_id].pop(name, None)
        if not t:
            return
        try:
            t.on_stop()
        except Exception as e:
            bus.shared.setdefault("task_errors", {})[f"stop:{name}"] = str(e)
        if self._owner.get(name) == core_id:
            self._owner[name] = None

    def _sync(self, core_id):
        for name, aff in list(self._aff.items()):
            should_run = (aff[core_id] == 1)
            is_running = (name in self._active[core_id])
            if should_run and not is_running:
                self._start_task(core_id, name)
            elif (not should_run) and is_running:
                self._stop_task(core_id, name)

    def _run_active(self, core_id):
        if not self._active[core_id]:
            return
        now_ms = time.ticks_ms()
        for name, t in list(self._active[core_id].items()):
            due = self._error_until_ms[core_id].get(name)
            if due is not None and time.ticks_diff(now_ms, due) < 0:
                continue
            try:
                t.loop()
            except Exception as e:
                bus.shared.setdefault("task_errors", {})[f"loop:{name}"] = str(e)
                self._error_until_ms[core_id][name] = time.ticks_add(now_ms, 1000)
                continue
            if getattr(t, "run_once", False):
                self._stop_task(core_id, name)
                self._aff[name] = (0, 0)

    def _boot_step(self, core_id):
        now_ms = time.ticks_ms()
        all_done = True
        for name, aff in list(self._aff.items()):
            if aff[core_id] != 1:
                continue
            t = self._ensure_task_instance(name)
            if not t:
                continue
            if getattr(t, "boot_done", False):
                continue
            due = self._boot_error_until_ms[core_id].get(name)
            if due is not None and time.ticks_diff(now_ms, due) < 0:
                all_done = False
                continue
            try:
                ok = t.on_boot()
            except Exception as e:
                bus.shared.setdefault("task_errors", {})[f"boot:{name}"] = str(e)
                self._boot_error_until_ms[core_id][name] = time.ticks_add(now_ms, 1000)
                all_done = False
                continue
            if not ok:
                all_done = False
        if all_done:
            bus.shared[f"core{core_id}_boot_done"] = True
        return all_done

    def _boot_barrier(self, core_id):
        while bus.shared.get("engine_run", True) and not bus.shared.get("boot_done"):
            self._boot_step(core_id)
            if bus.shared.get("core0_boot_done") and bus.shared.get("core1_boot_done"):
                if core_id == 0:
                    bus.shared["boot_done"] = True
                else:
                    time.sleep_ms(1)
            else:
                if bus.shared.get(f"core{core_id}_boot_done"):
                    time.sleep_ms(1)

    def runner_loop(self, core_id):
        self._boot_barrier(core_id)
        loops = 0
        t0 = time.ticks_ms()
        bus.shared.setdefault("perf", {})
        while bus.shared.get("engine_run", True):
            self._sync(core_id)
            self._run_active(core_id)
            loops += 1
            now = time.ticks_ms()
            dt = time.ticks_diff(now, t0)
            if dt >= 2000:
                bus.shared["perf"][f"core{core_id}_loop_ms"] = dt / max(1, loops)
                bus.shared["perf"][f"core{core_id}_loops_per_sec"] = (loops * 1000) / max(1, dt)
                loops = 0
                t0 = now
        for name in list(self._active[core_id].keys()):
            self._stop_task(core_id, name)

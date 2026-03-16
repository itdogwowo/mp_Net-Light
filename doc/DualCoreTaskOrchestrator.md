# 雙核心任務編排設計理念 (Dual-Core Task Orchestrator)

## 目標

此架構的核心目標是把「功能」與「CPU 核心」解耦，將系統拆成可註冊、可啟停、可遷移的任務 (Task)，並以雙核心各自的 Runner 進行無等待的高速輪詢，讓系統能在不中斷主流程的前提下持續擴充。

- 任務以生產者/消費者模型拆分，降低耦合、提升可替換性
- 任務在執行時可透過配置決定跑在 Core 0 或 Core 1
- 任務循環不使用 `time.sleep()` 來「卡住」CPU，而是透過「兩次執行差異時間」決定是否做事，未到時機就立刻返回，讓其他任務繼續被輪詢

## 關鍵原則

### 1) 任務必須是 Non-blocking

Task 的 `loop()` 必須遵循：

- 不做長時間阻塞 I/O
- 不做長時間計算（若必須，需拆成多步分段執行）
- 不使用 `sleep` 讓 CPU 停等
- 未到執行時機就立刻 `return`，由 Runner 以高頻輪詢再次喚起

Task 基類（精簡版）：

```python
class Task:
    def __init__(self, name, ctx):
        self.name = name
        self.ctx = ctx
        self.running = False
        self.run_once = False

    def on_start(self):
        self.running = True

    def loop(self):
        pass

    def on_stop(self):
        self.running = False
```

### 2) 以「時間差」控制節奏，而不是 `sleep`

典型寫法：

```python
now = time.ticks_us()
if time.ticks_diff(now, self.next_tick_us) < 0:
    return
self.next_tick_us = time.ticks_add(now, interval_us)
```

這樣做的效果是：

- CPU 永遠可用（能夠隨時插入新任務）
- 任務節奏精準（由 tick 驅動，而非睡眠誤差）
- 任何時序敏感任務都能被安排在同一顆 CPU 上，讓時序可控

時序敏感任務（渲染）通常會像這樣：未到時機就直接返回，把 CPU 留給同核其他任務。

```python
def loop(self):
    now = time.ticks_us()
    if time.ticks_diff(now, self.next_tick_us) < 0:
        return
    self.next_tick_us = time.ticks_add(self.next_tick_us, self.interval_us)
    self.consume_and_render_one_frame()
```

### 3) 生產者/消費者拆分與零拷貝資料通道

此專案的核心資料通道採用 `AtomicStreamHub`，其設計重點是：

- 預分配多個固定大小 buffer（避免執行時動態配置）
- 透過狀態機（IDLE/READY/READING）管理可寫/可讀槽位
- 讀取端可取得 `memoryview`（零拷貝視圖）並在下一次讀取時釋放

這使得跨核心的資料傳遞可以用「指標/狀態切換」完成，而不是靠鎖或大量複製，對時序敏感任務非常友好。

AtomicStreamHub（概念精簡版）：

```python
IDLE, READY, READING = 0, 1, 2

class AtomicStreamHub:
    def __init__(self, size, n=3):
        self._bufs = [bytearray(size) for _ in range(n)]
        self._views = [memoryview(b) for b in self._bufs]
        self._st = [IDLE] * n
        self._w = 0
        self._r = 0
        self._last = None

    def get_write_view(self):
        if self._st[self._w] != IDLE:
            return None
        return self._views[self._w]

    def commit(self):
        i = self._w
        if self._st[i] == IDLE:
            self._st[i] = READY
            self._w = (i + 1) % len(self._bufs)

    def get_read_view(self):
        if self._last is not None:
            self._st[self._last] = IDLE
            self._last = None
        i = self._r
        if self._st[i] == READY:
            self._st[i] = READING
            self._last = i
            self._r = (i + 1) % len(self._bufs)
            return self._views[i]
        return None
```

### 4) 核心互斥：任務不能同時跑在兩個核心

本設計要求任務 affinity 為 `(Core0, Core1)`，只能是：

- `(0,0)`：兩核都不跑（停用）
- `(1,0)`：只跑 Core 0
- `(0,1)`：只跑 Core 1

不允許 `(1,1)`，避免同一任務在兩核心同時執行造成狀態競爭。

## 架構組件

### 1) SysBus：服務註冊與共享狀態

- Service：共享大型物件/單例（例如 `pixel_stream`、`task_manager`）
- Provider：提供即時指標（例如 `render_fps`）
- shared：跨模組、跨核心的輕量共享狀態字典

SysBus（精簡版）：

```python
class SysBus:
    def __init__(self):
        self._services = {}
        self._providers = {}
        self.shared = {}
        self.slave_id = "UNKNOWN"

    def register_service(self, name, obj):
        if name in self._services:
            return False
        self._services[name] = obj
        return True

    def get_service(self, name):
        return self._services.get(name)

    def register_provider(self, key, func):
        if key in self._providers:
            return False
        self._providers[key] = func
        return True

    def get_metrics(self):
        res = {k: f() for k, f in self._providers.items()}
        res["slave_id"] = self.slave_id
        return res
```

### 2) TaskManager：任務註冊、親和性與 Runner

TaskManager 的責任：

- 註冊任務 class 與預設 affinity
- 在 Runner 迴圈中依 affinity 啟動/停止任務
- 支援「一次性任務」(run-once)：執行一次 loop 後自動停止並將 affinity 置為 `(0,0)`
- 提供效能回報：以固定時間窗口統計每顆核心的 loop 平均耗時與 loop/sec

TaskManager（概念精簡版，重點在 affinity / run-once / perf 窗口）：

```python
class TaskManager:
    def __init__(self, bus, ctx):
        self.bus = bus
        self.ctx = ctx
        self.task_cls = {}
        self.tasks = {}
        self.aff = {}
        self.run_once = {}
        self.active = {0: {}, 1: {}}
        self.bus.register_service("task_manager", self)

    def register_task(self, name, cls, affinity=(0,0), run_once=False):
        self.task_cls[name] = cls
        self.aff[name] = affinity
        self.run_once[name] = run_once

    def set_affinity(self, name, affinity):
        if affinity == (1,1):
            return False
        self.aff[name] = affinity
        return True

    def _sync(self, core_id):
        for name, aff in list(self.aff.items()):
            should = (aff[core_id] == 1)
            running = (name in self.active[core_id])
            if should and not running:
                if name not in self.tasks:
                    t = self.task_cls[name](name, self.ctx)
                    t.run_once = self.run_once.get(name, False)
                    self.tasks[name] = t
                t = self.tasks[name]
                t.on_start()
                self.active[core_id][name] = t
            if (not should) and running:
                t = self.active[core_id].pop(name)
                t.on_stop()

    def runner_loop(self, core_id):
        loops = 0
        t0 = time.ticks_ms()
        self.bus.shared.setdefault("perf", {})
        while self.bus.shared.get("engine_run", True):
            self._sync(core_id)
            for name, t in list(self.active[core_id].items()):
                t.loop()
                if t.run_once:
                    t.on_stop()
                    self.active[core_id].pop(name, None)
                    self.aff[name] = (0,0)
            loops += 1
            now = time.ticks_ms()
            dt = time.ticks_diff(now, t0)
            if dt >= 2000:
                self.bus.shared["perf"][f"core{core_id}_loop_ms"] = dt / max(1, loops)
                self.bus.shared["perf"][f"core{core_id}_loops_per_sec"] = (loops * 1000) / dt
                loops = 0
                t0 = now
```

### 3) 典型任務

- NetworkTask：網路輪詢、控制通道、供應鏈邏輯（偏生產者）
- RenderTask：從 `AtomicStreamHub` 消費影格並輸出到 LED（偏消費者、時序敏感）
- WebUITask：簡易 HTTP 入口，用於緊急控制與觀測

這三類任務的共通點：

- `loop()` 只做「可快速完成的一小步」
- 未達時機就 `return`
- I/O 使用非阻塞 socket（或拆分成多次輪詢）

## 啟動流程與任務註冊

啟動時：

1. 初始化硬體服務（LED、NetworkManager 等）
2. 建立 `AtomicStreamHub` 並註冊為 `pixel_stream`
3. 建立 `App`（Schema/Dispatcher/Parser）
4. 建立 `TaskManager`，註冊任務與預設 affinity
5. Core 1 啟動 Runner（thread）
6. Core 0 以主線程跑 Runner（常駐）

啟動流程（精簡版）：

```python
bus.shared["engine_run"] = True
bus.register_service("pixel_stream", AtomicStreamHub(size))

app = App()
ctx = {"app": app, "bus": bus, "st_LED": st_LED}
tm = TaskManager(bus, ctx)

tm.register_task("network", NetworkTask, (1,0))
tm.register_task("web_ui",  WebUITask,  (1,0))
tm.register_task("render",  RenderTask, (0,1))

_thread.start_new_thread(tm.runner_loop, (1,))
tm.runner_loop(0)
```

## Online 調度與遷移

### 1) 動態調整任務 affinity

```python
from lib.sys_bus import bus
tm = bus.get_service("task_manager")

tm.set_affinity("network", (1, 0))
tm.set_affinity("render", (0, 1))
tm.set_affinity("web_ui", (1, 0))
```

### 2) 一次性任務 (Run-once)

```python
tm.register_task("self_check", SelfCheckTask, default_affinity=(1, 0), run_once=True)
```

run-once 任務會在 Runner 偵測到執行後自動停用，避免被下一輪 `_update_tasks()` 重新啟動。

## 迷你回報系統 (Performance Metrics)

TaskManager 會以固定時間窗口（目前為 2 秒）計算：

- `core{N}_loop_ms`：平均每次 Runner loop 的耗時（ms/loop）
- `core{N}_loops_per_sec`：Runner loop 的頻率（Hz）

這些數據會寫入 `bus.shared["perf"]`，並可由 Web UI 以 `/api/perf` 讀取。

Web UI / API（精簡版：回傳 perf）：

```python
def handle_request(path):
    if path == "/api/perf":
        return json.dumps(bus.shared.get("perf", {}))
```

## 任務撰寫規範 (建議)

- `on_start()`：做一次性初始化（盡量預分配 buffer），避免 loop 中頻繁 malloc
- `loop()`：只做「可快速完成」的一小段工作；未到時機立刻返回
- 使用 `ticks_ms/us` 控制節奏，不使用 sleep
- 若任務含 IO（socket、檔案），優先使用非阻塞模式與小步輪詢

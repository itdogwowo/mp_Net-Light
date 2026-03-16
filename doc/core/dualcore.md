# 雙核心架構（DualCore）

本文件描述 Slave 端「雙核心任務框架」如何運作、如何使用，以及它和 NetBus / AtomicStreamHub / Proto 的協作界面。

## 目的與核心概念

- 用 Task 把系統拆成可獨立啟停的單元，並以 affinity 決定跑在 Core0 或 Core1。
- 以 non-blocking 的輪詢排程取代 sleep 型阻塞，讓「網路穩定」與「渲染穩定」同時成立。

對應入口：
- 啟動與任務配置：[slave/main.py](../../slave/main.py#L10-L38)
- Task 基類（生命周期）：[task.py](../../slave/lib/task.py#L1-L20)
- 調度器（TaskManager）：[task_manager.py](../../slave/lib/task_manager.py#L1-L181)

## 任務生命周期（你應該怎麼寫 Task）

Task 具備四個主要 hook：

- on_boot()：開機初始化階段，可回傳 False 表示尚未完成，下一輪再試  
  預設行為：[task.py](../../slave/lib/task.py#L9-L12)
- on_start()：被排程到某 core 開始跑時呼叫
- loop()：高頻被呼叫的工作函數（必須 non-blocking）
- on_stop()：被移出該 core 或關機時呼叫

## Boot Barrier（兩核心都完成 on_boot 才進入 loop）

TaskManager 會在每顆核心進入 runner_loop 前先跑 boot barrier：

- 每顆 core 對「affinity 該 core=1 的任務」反覆呼叫 on_boot()，直到都完成  
  [task_manager.py](../../slave/lib/task_manager.py#L124-L163)
- 兩顆 core 都完成後，由 Core0 設定 bus.shared["boot_done"]=True 才進入正常排程  
  [task_manager.py](../../slave/lib/task_manager.py#L152-L163)

設計要點：
- on_boot() 不是「全域一次」；它是「每顆核心只對自己要跑的任務」做 boot 完成確認。
- on_boot() 允許拆步（回 False），避免在開機時做長阻塞。

## Affinity（任務跑在哪顆核心）

TaskManager 使用 (core0, core1) 這種二元 tuple：

- (1,0)：只跑 Core0
- (0,1)：只跑 Core1
- (0,0)：停用
- (1,1)：禁止（避免同一個 Task 同時在兩核心跑）  
  [task_manager.py](../../slave/lib/task_manager.py#L59-L63)

### 設定方式（啟動時）

啟動入口會註冊任務與 affinity：
- Core0：network / supply_chain / heartbeat
- Core1：render / fs_scan  
  [main.py](../../slave/main.py#L28-L37)

### 設定方式（執行期間）

執行中可呼叫：
- tm.set_affinity(name, affinity)  
  [task_manager.py](../../slave/lib/task_manager.py#L59-L63)

注意：
- 切換不是搶斷式；要等 loop() 返回，runner 才能進入下一輪 sync。
- Task instance 是同一個物件在不同 core 間移動（狀態會保留），需要 reset 請放在 on_stop/on_start 做。

## Runner Loop（排程與容錯）

runner_loop 的核心工作：

- _sync：依 affinity 啟動/停止任務  
  [task_manager.py](../../slave/lib/task_manager.py#L97-L105)
- _run_active：逐一呼叫 task.loop()，並對例外做退避（1 秒）避免卡死  
  [task_manager.py](../../slave/lib/task_manager.py#L106-L123)
- perf：每 2 秒輸出每 core 的 loop_ms 與 loops_per_sec 到 bus.shared["perf"]  
  [task_manager.py](../../slave/lib/task_manager.py#L164-L179)

## 與其他核心模組的協作界面

### DualCore ↔ NetBus

- NetworkTask（Core0）會建立 UDP/WS 的 NetBus 並在 loop 中輪詢  
  [network.py](../../slave/tasks/network.py#L12-L118)
- NetBus 的設計要求：poll 必須 non-blocking（socket timeout=0），符合 runner 模型  
  [net_bus.py](../../slave/lib/net_bus.py#L56-L57)

### DualCore ↔ AtomicStreamHub

- TaskManager 會在 register_task 時嘗試確保 pixel_stream（AtomicStreamHub）存在  
  [task_manager.py](../../slave/lib/task_manager.py#L21-L46)
- Core0 寫入（SupplyChain）；Core1 讀取並渲染（Render）  
  [supply_chain.py](../../slave/tasks/supply_chain.py#L21-L39) / [render.py](../../slave/tasks/render.py#L27-L65)

### DualCore ↔ Proto（以及 App/Dispatcher）

- NetworkTask 的 NetBus 會把 bytes 交給 App.handle_stream → StreamParser.pop → Dispatcher.dispatch  
  [net_bus.py](../../slave/lib/net_bus.py#L119-L126) → [app.py](../../slave/app.py#L28-L46)

## 實務建議（避免常見坑）

- loop() 內避免長時間阻塞 I/O（例如大檔案一次性 read）；要拆成小步輪詢。
- 用 ticks_ms/us 做節奏控制，而不是 sleep；未到時機就 return。
- 跨核心交換大型資料只走 AtomicStreamHub；跨核心同步狀態只走 bus.shared 並保持 key 粒度小。

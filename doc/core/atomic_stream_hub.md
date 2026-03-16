# AtomicStreamHub（AtomicStreamHub / pixel_stream）

AtomicStreamHub 是 Slave 端跨核心交換「影格資料」的核心通道。它用預分配多緩衝 + 狀態機（IDLE/READY/READING）達成：

- 生產者（Core0）可以持續寫入下一批資料
- 消費者（Core1）可以穩定讀取上一批資料
- 不需要鎖、不需要在跨核心間搬移大量資料（可用 memoryview 零拷貝）

對應實作：[buffer_hub.py](../../slave/lib/buffer_hub.py)

## 這個模組的「責任邊界」

- 只管理「固定大小的 bytes 緩衝」與「可寫/可讀狀態」。
- 不關心資料語意（是不是 LED、是不是檔案、是不是測試圖樣）。
- 不關心資料來源（網路、SD、產生器）；來源在上層 task/action。

## 兩種使用模式

AtomicStreamHub 提供兩種 API 風格，兩者可以共存：

### A) 複製模式（write_from / read_into）

- 適合：上層已經有完整 bytes/bytearray，需要一次性拷貝進 hub。
- 入口：[buffer_hub.py](../../slave/lib/buffer_hub.py#L46-L96)

典型用法（直接寫像素資料）：
- STREAM Direct Mode 會用 write_from 把 pixel_data 拷貝進 hub  
  [stream_actions.py](../../slave/action/stream_actions.py#L110-L117)

### B) 零拷貝模式（get_write_view / commit / get_read_view）

- 適合：資料來源支援 readinto(memoryview) 或逐段填入，避免額外拷貝。
- 入口：[buffer_hub.py](../../slave/lib/buffer_hub.py#L124-L165)

生產端（Core0）典型流程：
1. view = hub.get_write_view()
2. 把資料填進 view（例如 file.readinto(view) 或分段寫）
3. hub.commit()

消費端（Core1）典型流程：
1. view = hub.get_read_view()
2. 若 view 不是 None，取出本次可用資料並渲染
3. 下一次再 get_read_view() 時會自動釋放上一個 READING 槽位  
   [buffer_hub.py](../../slave/lib/buffer_hub.py#L152-L165)

## 在本專案的實際接線方式

### Service 名稱：pixel_stream

AtomicStreamHub 以 SysBus service 的形式被註冊為 pixel_stream：
- TaskManager 在 register_task 時嘗試自動建立並註冊  
  [task_manager.py](../../slave/lib/task_manager.py#L21-L46)

大小計算邏輯：
- size = st_LED.total_bytes * buffer_frames
- buffer_frames 來自 bus.shared["System"]["buffer_frames"]（由 boot/config 裝入）  
  [task_manager.py](../../slave/lib/task_manager.py#L29-L46)

### 生產端：SupplyChainTask（Core0）

SupplyChainTask 定期呼叫 handle_supply_chain，把檔案或測試 pattern 填入 hub：
- [supply_chain.py](../../slave/tasks/supply_chain.py#L21-L39)
- [stream_actions.py](../../slave/action/stream_actions.py#L37-L109)

其中 readinto(view) + commit 是典型零拷貝路徑：
- [stream_actions.py](../../slave/action/stream_actions.py#L81-L109)

### 消費端：RenderTask（Core1）

RenderTask 以固定 FPS 讀取 hub 的 read_view，切片取出 frame_size 逐幀輸出：
- [render.py](../../slave/tasks/render.py#L51-L65)

## Flush 與積壓

- flush() 只重設狀態與指標，不清空內容，適合在 seek / 切檔時快速丟棄舊資料  
  [buffer_hub.py](../../slave/lib/buffer_hub.py#L97-L111)
- get_fill_level() 可用於觀察 READY 積壓（除錯/觀測用）  
  [buffer_hub.py](../../slave/lib/buffer_hub.py#L112-L120)

## 常見使用規範（建議）

- 生產端：拿到 write_view 之後要盡快填完並 commit；拿不到（None）代表 hub 滿了，應該 return 等下一輪。
- 消費端：get_read_view() 回 None 代表沒有新資料，不要 busy-wait 做額外工作。
- 跨核心大型資料只走 hub；不要把大 bytearray 放進 bus.shared（shared 適合小狀態）。

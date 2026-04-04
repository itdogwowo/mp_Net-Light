# Display Service / Task

本文件描述 `display` service 與 `DisplayTask` 的用途與使用方式。它的目標是把 `jpeg_decoder` 的輸出（block_hub）送到 TFT (`lcd` service) 上。

## 依賴關係

- TFT 初始化：由 [boot.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/boot.py) 的 `init_display()` 依 `config.json` 的 `TFT`（向後相容 `Display`）建立並註冊：
  - `bus.get_service("lcd")`
  - `bus.get_service("tft")`（別名）
- JPEG 解碼：由 `jpeg_decoder` service + `jpeg_decode` task 負責。
  - `DisplayTask` 僅消費 `jpeg_decoder.output[*].block_hub`。

## display service

註冊於 `bus.get_service("display")`，由 [display_service.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/display_service.py) 建立。

欄位：
- `enable`: 開關（預設 True）
- `displayed_blocks`: 顯示過的 blocks 數量（metrics provider：`display_blocks`）
- `last_err`, `last_ms`
- `rr`: output list 輪詢指標

## DisplayTask

程式碼位於 [display_task.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/tasks/display_task.py)。

行為：
- 取得 `lcd`（或 `tft`）service，若不存在就不做事。
- 取得 `jpeg_decoder`（或 `jepg_decoder`）service，若未啟用就不做事。
- 以 round-robin 方式掃描 `jpeg_decoder.output[]`，每輪最多消費一個 block：
  - `rv = output[i].block_hub.get_read_view()`
  - `unpack_block_header(rv)` 取得 `(payload_len, seq, x, y, w, h, flags, fmt)`
  - `lcd.set_window(x, y, x+w-1, y+h-1)`
  - `lcd.write_data(payload)`

## 啟用方式

`DisplayTask` 預設在 [main.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/main.py) 以 affinity `(0,0)` 註冊，不會自動啟動。

你可以在 Scheduler 決定要顯示時動態啟用：

```python
tm = bus.get_service("task_manager")
tm.set_affinity("display", (0, 1))
```

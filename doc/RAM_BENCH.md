# RAM_BENCH.md — 純 RAM 上傳測速（新版本）

本文件記錄近期針對「純 RAM 測速」的更新：新增一套獨立的 RAM_BENCH 協議與 Slave handler，並更新 `NetBusMaster_to_test.py` 的測試選單以使用新流程。

---

## 1) 為什麼要新增 RAM_BENCH？

舊版 `NetBusMaster_to_test.py` 的：
- **7. RAM Speed Test**：實際上走的是檔案上傳指令 `0x2001/0x2002/0x2003`（FILE_*）。在目前 Slave 實作中，這會落到 `FSManager` 的寫檔流程，並非純 RAM 測速。
- **8. Raw Stream Test**：工具端把 `0x2007` 當成「Enter Raw Mode」再直接灌 raw bytes，但目前 Slave 端 `0x2007` 是 `FILE_READ`（schema/handler 定義不同），因此此測試與現行協議已脫節。

因此新增一套 **不寫檔、只做 RAM 消耗與統計** 的 RAM_BENCH 指令，讓測試結果更乾淨、可控、且不會與檔案傳輸流程互相干擾。

---

## 2) RAM_BENCH 指令表（V4 協議外掛）

Schema 檔：`/schema/ram_bench.json`（Repo 對應：`slave/schema/ram_bench.json`）

| CMD | Name | 方向 | 用途 |
|---|---|---|---|
| 0x1811 | RAM_BENCH_START | PC → Slave | 開始一次 RAM 測速 session |
| 0x1812 | RAM_BENCH_CHUNK | PC → Slave | 送一個資料 chunk（payload: bytes_rest） |
| 0x1813 | RAM_BENCH_STOP | PC → Slave | 結束 session，觸發統計回報 |
| 0x1814 | RAM_BENCH_REPORT | Slave → PC | 回報本次 session 的 bytes/chunks/elapsed/速率 |

### RAM_BENCH_START 參數
- `run_id (u16)`：本次測試 ID（PC 端產生）
- `total_size (u32)`：預計送多少 bytes（用於 UI/進度）
- `chunk_size (u16)`：每包 data 大小（建議 4096~16384）
- `mode (u8)`
  - `0`：discard（只統計 bytes/chunks，不做 memcpy）
  - `1`：copy（把 data copy 進 ring buffer，模擬「落 RAM/PSRAM」的 memcpy 成本）
-  `2`：hub_copy（把 data copy 進 AtomicStreamHub，模擬「跨階段移交」的成本）
- `ring_kb (u16)`：copy 模式的 ring buffer 大小（KB）
  - mode=1：Ring KB
  - mode=2：Hub buffers（槽位數；建議 4~16）

### RAM_BENCH_REPORT 回報值
- `mb_s_x1000 (u32)`：吞吐 MB/s 的 1000 倍（例如 6123 代表 6.123 MB/s）

---

## 3) Slave 端實作位置

- Handler：`slave/action/ram_bench_actions.py`
- 註冊入口：`slave/action/registry.py`（確保開機時註冊到 Dispatcher）

行為摘要：
- START：建立 session、紀錄起始時間與 counters；copy 模式會嘗試配置 ring buffer。
- CHUNK：累加 bytes/chunks；copy 模式做 ring 寫入（固定大小循環覆蓋）。
- STOP：計算 elapsed_ms 與速率，送 `RAM_BENCH_REPORT` 回 PC。

---

## 4) PC 工具端：NetBusMaster Step 7（新流程）

檔案：`tools/NetBusMaster_to_test.py`

Step 7 目前行為：
1. 送 `RAM_BENCH_START(0x1811)`
2. 連續送 `RAM_BENCH_CHUNK(0x1812)`（每次帶 `seq` 與 `data`）
3. 送 `RAM_BENCH_STOP(0x1813)`，等待 `RAM_BENCH_REPORT(0x1814)` 回報並印出結果

建議參數：
- `chunk_size`：16384（常見最穩），或 4096（更貼近小包控制流）
- `mode=0`：量測「協議/解碼/dispatch」本身的吞吐
- `mode=1`：量測「協議/解碼/dispatch + memcpy 落 RAM」的吞吐

---

## 4.1) 目標 1–2MB/s 的實務建議（吞吐瓶頸排查）

若你看到吞吐卡在數百 KB/s（例如 ~600KB/s），通常不是 CRC/解碼，而是「框架性開銷」造成。

### A) 逐包列印（print）幾乎必定是第一號瓶頸
- Dispatcher 在 debug_level >= 1 時會對每個指令列印一行。
- RAM_BENCH_CHUNK 屬於高頻指令，逐包列印會顯著壓低吞吐。
- 目前已對 `0x1812 (RAM_BENCH_CHUNK)` 進行靜音（不逐包列印），其餘指令仍可正常輸出。

### B) Buffer/Chunk 設定要匹配
建議先用以下組合找上限：
- `chunk_size=16384`
- `Buffer.size >= 16384`（否則容易變成多次 recv、多次 feed）

### C) AtomicStreamHub 的正確用法（避免 Hub 塞滿）
若 `Buffer.rx_hub_buffers > 0` 啟用接收 Hub：
- 需要成對進行「寫入(commit) → 讀取(get_read_view)」以釋放槽位
- 否則會在提交幾次後把 Hub 塞滿，導致 `get_write_view()` 返 None，進而出現 drop/drain 行為或吞吐崩落

目前 NetBus 已修正：commit 後會立即取出 read_view 作為本次 raw buffer 使用，並在下次讀取時釋放上一個 READING buffer，避免積壓。

### D) Hub 滿載時的策略
NetBus 支援 `Buffer.drop_on_full`：
- `0`：Hub 滿就直接 return（對 TCP/WS 會形成 backpressure；UDP 由 OS buffer 決定是否 drop）
- `1`：Hub 滿時會讀取一小段資料丟棄以清空 socket（可用於「寧可丟包也要保持互動」的情境）

建議做吞吐上限量測時先用 `drop_on_full=0`，避免「丟包式 drain」影響結果。

---

## 5) Step 8（Raw Stream Test）狀態

Step 8 已在工具端停用，原因是 Raw Mode 的「進入指令」與目前 Slave schema/handler 不一致，容易造成錯誤測試與連線混亂。

---

## 6) 連線重啟（同 URL 需要可重連）

使用場景：測試期間常會重啟 PC 端工具程式，若 Slave 端一律「同 URL 且 connected 就不重連」，會導致 MCU 仍黏住舊連線，最後只能重啟 MCU。

現行策略（在 `sys_actions.py` 的 connect 流程）：
- 同 URL/同 peer 時，不會無條件跳過重連；會先做連線存活檢查。
- 若判定連線已失效，會主動斷線後重連，避免必須重啟 MCU。

---

## 7) SchemaCodec 行為更新：bytes_rest 變為 memoryview

為減少大 payload 的額外拷貝，`SchemaCodec.decode()` 的 `bytes_rest` 欄位現在回傳 **memoryview**（bytes-like），而不是 bytes。

影響面：
- handler 若只用 `len(data)` / `file.write(data)` / `sock.send(data)`：通常不需修改（buffer protocol 可直接用）。
- 若 handler 依賴 `isinstance(data, bytes)` 或對 bytes 做 `.decode()`：需自行 `bytes(data)` 轉型。

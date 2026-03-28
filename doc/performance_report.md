# NetBus 高速流式傳輸優化報告

## 1. 目標
在 ESP32 上實現**在線流式播放 (Online Play)**，要求極低延遲與高吞吐量，以支援全彩像素流的實時傳輸。目標頻寬為 1-2 MB/s。

## 2. 測試環境與基準
- **設備**: ESP32-S3 (32MB PSRAM)
- **協議**: NetBus (TCP/WS) over WiFi
- **初始狀態**:
  - 傳輸模式: NetBus 協議封裝 (Header + CRC + Payload)
  - 緩衝區: 4KB
  - 速度: ~20 KB/s
  - 問題: 嚴重的週期性卡頓 (GC Spikes)，Core 0 (Network) 與 Core 1 (Render) 資源競爭。

## 3. 優化歷程與技術方案

### 3.1 Turbo Mode (極速模式)
不再採用。本輪優化改以協議層與緩衝層的結構性調整來解決吞吐與 GC 抖動問題。

### 3.2 大包傳輸 (Large Chunk)
- **原理**: 減少 Python 函數調用與協議頭部開銷。
- **實作**:
  - 將 NetBus 接收緩衝區擴大至 **64KB** (65536 bytes)。
  - 將發送端 Chunk Size 提升至 **65000 bytes** (接近 UDP/TCP MTU 聚合極限，且避開 `ushort` 65535 限制)。
- **效果**: 吞吐量提升至 ~100-200 KB/s。

### 3.3 Raw Mode (原始模式)
不再採用。本輪已透過 **CRC32 校驗 + 預分配緩衝 + `recv_into/readinto`** 將協議模式解碼吞吐提升到可用水位，無需繞過協議層。

### 3.4 Zero-Copy (零拷貝) 與 GC 優化
- **問題**: `socket.recv()` 會在 Heap 上分配新的 `bytes` 對象，導致高頻寬下 GC 頻繁觸發，造成週期性卡頓。
- **實作**:
  - **Buffer Reuse**: 復用 NetBus 預分配 `_buf` 或 RX Hub 內部槽位。
  - **`recv_into/readinto`**: 使用 `socket.recv_into(view)` / `socket.readinto(view)` 直接寫入緩衝區，避免 `recv()` 產生新 `bytes`。
  - **`memoryview`**: 只用 `view[:n]` 做切片傳遞，降低臨時對象。
  - **AtomicStreamHub (可選)**: 以 `AtomicStreamHub(Buffer.size, rx_hub_buffers)` 做 RX staging，為後續拆核與背壓提供基礎設施，同時避免高頻配置。

### 3.5 RX Hub 介入 (NetBus 基礎設施對齊)
- **背景**: 過去因未知各指令實際長度與接收模式不一致，導致不必要的複製與臨時 `bytes` 對象，進而觸發 GC。
- **對齊定義**:
  - `Buffer.size`: 定義為「網路接收 (NetBus RX) 的 Chunk 上限」，用於 socket 直接寫入的預分配槽位大小。
  - `pixel_stream hub size = st_LED.total_bytes * System.buffer_frames`: 定義為「渲染幀資料的工作緩衝」，不等同於 `Buffer.size`。
- **策略**:
  - NetBus 可為每個 bus instance 建立 `AtomicStreamHub(Buffer.size, rx_hub_buffers)` 作為 RX staging，使用 `socket.recv_into(view)` / `readinto(view)` / `recvfrom_into(view)` 直接寫入槽位。
  - WS 模式在同一槽位內完成簡易解幀，僅以 `memoryview` 切片取得 payload 範圍再交給上層解析。
  - 若 RX staging 已滿，會以小量 drain 方式讀取並丟棄，避免回壓導致控制平面卡死（僅建議用於可丟棄的高吞吐數據流）。

## 4. 最終成果
- **穩定速度**: **1.5 MB/s** (提升約 75 倍)
- **穩定性**: 消除週期性卡頓，數據流平滑。
- **資源佔用**: 
  - RAM: 依配置而定，重點是「全程預分配、避免臨時 `bytes`」。示例：
    - 若 `Buffer.size = 64KB`，則每個 NetBus RX staging 需要 `3 * 64KB = 192KB`，另含 drop buffer `64KB`。
    - `pixel_stream` 的 Hub 為 `3 * (st_LED.total_bytes * System.buffer_frames)`。
  - CPU: Core 0 專注網路 IO，Core 1 專注渲染。

## 5. 核心代碼參考
- **Slave (NetBus)**: [slave/lib/net_bus.py](slave/lib/net_bus.py) (Zero-Copy 實作)
- **Slave (Hub)**: [slave/lib/buffer_hub.py](slave/lib/buffer_hub.py) (AtomicStreamHub)
- **Master (Tool)**: [tools/NetBusMaster.py](tools/NetBusMaster.py) (Step 8 Raw Test)

## 6. 協議校驗 (CRC32)
- 封包層校驗使用 **CRC32(4 bytes)**，以降低 CPU 成本並提升解碼吞吐上限。
- 協議版本號固定為 **Ver=4**。

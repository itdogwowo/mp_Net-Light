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
- **原理**: 在傳輸期間暫停非必要的背景任務。
- **實作**:
  - 禁用心跳包 (Heartbeat)。
  - 禁用狀態回報 (Status Report)。
  - 暫停主循環的 GC 檢查。
  - Core 1 渲染引擎在緩衝區為空時主動 `sleep(1ms)` 禮讓 CPU 給 Core 0。

### 3.2 大包傳輸 (Large Chunk)
- **原理**: 減少 Python 函數調用與協議頭部開銷。
- **實作**:
  - 將 NetBus 接收緩衝區擴大至 **64KB** (65536 bytes)。
  - 將發送端 Chunk Size 提升至 **65000 bytes** (接近 UDP/TCP MTU 聚合極限，且避開 `ushort` 65535 限制)。
- **效果**: 吞吐量提升至 ~100-200 KB/s。

### 3.3 Raw Mode (原始模式)
- **原理**: 繞過 NetBus 協議層的解析開銷，直接操作 TCP Socket。
- **實作**:
  - 新增指令 `0x2007 (FILE_RAW_BEGIN)`。
  - 進入 Raw Mode 後，Socket 數據不再經過 Parser，直接導向 Stream Hub。
  - 傳輸結束後自動切回協議模式。

### 3.4 Zero-Copy (零拷貝) 與 GC 優化
- **問題**: `socket.recv()` 會在 Heap 上分配新的 `bytes` 對象，導致高頻寬下 GC 頻繁觸發，造成週期性卡頓。
- **實作**:
  - **Buffer Reuse**: 復用 NetBus 預分配的 64KB `_buf`。
  - **`readinto`**: 使用 `socket.readinto(view)` 直接寫入緩衝區。
  - **`memoryview`**: 使用切片 `view[:n]` 傳遞數據，全程無新對象產生。
  - **Triple Buffering**: `AtomicStreamHub` 配置為 3 個 64KB 緩衝區 (共 192KB)，實現 Core 0 寫入與 Core 1 讀取的無鎖並發。

### 3.5 RX Hub 介入 (NetBus 基礎設施對齊)
- **背景**: 過去因未知各指令實際長度與接收模式不一致，導致不必要的複製與臨時 `bytes` 對象，進而觸發 GC。
- **對齊定義**:
  - `Buffer.size`: 定義為「網路接收 (NetBus RX) 的 Chunk 上限」，用於 socket 直接寫入的預分配槽位大小。
  - `pixel_stream hub size = st_LED.total_bytes * System.buffer_frames`: 定義為「渲染幀資料的工作緩衝」，不等同於 `Buffer.size`。
- **策略**:
  - NetBus 為每個 bus instance 建立 `AtomicStreamHub(Buffer.size)` 作為 RX staging，使用 `socket.readinto(view)` / `recvfrom_into(view)` 直接寫入槽位。
  - WS 模式在同一槽位內完成簡易解幀，僅以 `memoryview` 切片取得 payload 範圍再交給上層解析。
  - 若 RX staging 已滿，仍持續讀取 socket 但丟棄資料 (drop drain) 以避免 TCP 回壓造成上游卡死；丟棄策略僅適用於可丟棄的高吞吐流量，控制類命令需另行保證可達性。

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

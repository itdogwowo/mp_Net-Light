# AI_CONTEXT — mp_Net-Light 統一背景文件（整理版）

本文件提供「全局大圖」：專案目標、核心架構分工、資料流與擴展約束。細節請搭配 core/ 內的拆分文件閱讀。

建議入口：[doc/README.md](../README.md)

## 1) 專案概述

mp_Net-Light 是一個 Server ⇄ MicroPython Client（ESP32）傳輸控制系統，用於高頻率、低延遲地驅動燈光/LED 影格與狀態控制。

設計目標：
- 低延遲、封包可驗證（CRC）、可在 byte stream 上穩定重同步
- 多通道統一（WS/UDP/TCP）但上層處理流程一致
- 雙核心分工（Core0 網路/供給；Core1 渲染）以避免互相拖累

## 2) 系統主要元件與分層

### Slave（MicroPython/ESP32）

- 啟動入口（雙核心任務）：[slave/main.py](../../slave/main.py)
- 裝配層（Schema + Dispatcher + Action 註冊）：[slave/app.py](../../slave/app.py)
- 協議封包與解析：[slave/lib/proto.py](../../slave/lib/proto.py)
- 傳輸統一層（TCP/WS/UDP）：[slave/lib/net_bus.py](../../slave/lib/net_bus.py)
- 跨核心影格緩衝：[slave/lib/buffer_hub.py](../../slave/lib/buffer_hub.py)
- 任務調度器：[slave/lib/task_manager.py](../../slave/lib/task_manager.py)

### Server（Django + Channels）

- NL3 封包封裝（pack/unpack）：[server/core/protocol.py](../../server/core/protocol.py)
- WS bytes_data 下發：[server/core/bus_manager.py](../../server/core/bus_manager.py)
- UDP discovery 監聽：[/server/core/discovery.py](../../server/core/discovery.py)

## 3) 核心資料流（兩條最重要的路徑）

### A) 控制資料流（網路 → 指令 → action）

1. NetBus.poll() 收到 bytes 後交給 App.handle_stream()  
   [net_bus.py](../../slave/lib/net_bus.py#L87-L132) → [app.py](../../slave/app.py#L28-L46)
2. App 透過 StreamParser.pop() 解析出 0..N 個封包後 dispatch 到對應 handler  
   [proto.py](../../slave/lib/proto.py#L62-L102) → [app.py](../../slave/app.py#L41-L46)
3. handler 依 schema 解碼後得到 args(dict)，只處理語意與狀態變更（通常透過 SysBus）  
   action 註冊入口：[registry.py](../../slave/action/registry.py)

### B) 影格資料流（供給 → AtomicStreamHub → 渲染）

1. Core0 生產者把影格寫入 pixel_stream（AtomicStreamHub）並 commit  
2. Core1 消費者依 FPS 讀取 pixel_stream 的 read_view 並輸出到 LED

對應實例：
- 生產端：[SupplyChainTask](../../slave/tasks/supply_chain.py)
- 消費端：[RenderTask](../../slave/tasks/render.py)

## 4) 協議要點（NL3 + Schema）

- NL3 封包：SOF=b"NL"、VER=3、CRC16（校驗範圍不含 SOF 與 CRC）  
  [proto.py](../../slave/lib/proto.py#L27-L60)
- payload 由 /slave/schema/*.json 定義並由 schema_codec 解碼為 dict，減少手寫 bytes offset  
  Schema 入口：[slave/schema](../../slave/schema)

## 5) 擴展約束與最佳實踐（務必遵守）

- Task.loop 必須 non-blocking；用 tick 控制節奏，未到時機就 return（不要用長 sleep 卡住 runner）。
- 大型資料跨核心交換只走 AtomicStreamHub；bus.shared 僅用於小狀態旗標。
- NetBus 只管 bytes 的收發與餵入，不在 NetBus 內寫業務邏輯。
- Proto 只管封包與流式解析；語意層在 Schema + action handlers。

## 6) 對應的拆分文件（細節）

- 雙核心架構：[core/dualcore.md](../core/dualcore.md)
- NetBus：[core/net_bus.md](../core/net_bus.md)
- AtomicStreamHub：[core/atomic_stream_hub.md](../core/atomic_stream_hub.md)
- Proto：[core/proto.md](../core/proto.md)

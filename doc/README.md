# mp_Net-Light 文件索引

本目錄集中整理專案所有文件，並以「可獨立閱讀、可組合運作」為原則：雙核心架構、NetBus、AtomicStreamHub、Proto 各自解耦，但透過 App + SysBus 串起完整資料流。

## 建議閱讀順序

1. 核心總覽：本頁
2. 雙核心架構：[core/dualcore.md](core/dualcore.md)
3. 網路通道統一層：[core/net_bus.md](core/net_bus.md)
4. 跨核心影格通道：[core/atomic_stream_hub.md](core/atomic_stream_hub.md)
5. 協議封包與流式解析：[core/proto.md](core/proto.md)

## 四大核心模組（分工邊界）

- 雙核心架構：決定「工作怎麼被切成任務」與「任務跑在哪顆核心」  
  入口：[slave/main.py](../slave/main.py) + [slave/lib/task_manager.py](../slave/lib/task_manager.py)
- NetBus：統一 TCP/WS/UDP 的收發與非阻塞輪詢，並把 bytes 流餵進 App 解析/分發  
  入口：[slave/lib/net_bus.py](../slave/lib/net_bus.py)
- AtomicStreamHub：跨核心「影格緩衝交換」的唯一通道（多緩衝 + 狀態機）  
  入口：[slave/lib/buffer_hub.py](../slave/lib/buffer_hub.py)
- Proto：NL3 封包格式與 StreamParser（黏包/拆包、SOF 重同步、CRC）  
  入口：[slave/lib/proto.py](../slave/lib/proto.py)

## 它們如何「互相獨立」但「緊密合作」

### 1) 控制資料流（網路 → 指令 → 狀態/行為）

1. NetworkTask 建立兩條通道：UDP discovery + WS control  
   [tasks/network.py](../slave/tasks/network.py)
2. NetBus.poll() 接收 bytes（必要時做 WS 解幀）後交給 App.handle_stream()  
   [net_bus.py](../slave/lib/net_bus.py#L87-L132) → [app.py](../slave/app.py#L28-L46)
3. App 用 StreamParser 解析出 NL3 封包後，由 Dispatcher 依 cmd 分發到對應 action handler  
   [proto.py](../slave/lib/proto.py#L62-L102) → [app.py](../slave/app.py#L41-L46)
4. action handler 透過 SysBus（services/providers/shared）改變系統狀態或呼叫服務  
   例如串流播放狀態：[stream_actions.py](../slave/action/stream_actions.py#L6-L36)

### 2) 影格資料流（影格生產 → 跨核心交換 → 渲染）

1. Core0 端生產者（例如 SupplyChainTask）把影格寫進 AtomicStreamHub，commit 後變成可讀  
   [tasks/supply_chain.py](../slave/tasks/supply_chain.py#L21-L39) → [stream_actions.py](../slave/action/stream_actions.py#L37-L109)
2. Core1 端消費者（RenderTask）以固定 FPS 節奏讀取 AtomicStreamHub 的 read_view，寫入 LED buffer 並 show  
   [tasks/render.py](../slave/tasks/render.py#L27-L65)

### 3) 解耦關鍵：只有「接口」彼此知道

- NetBus 不需要知道 LED，也不需要知道每個 cmd 的語意；它只負責「收/發」與「餵 bytes」。
- Proto/Schema/Dispatcher 不需要知道網路通道是 UDP 還是 WS；它只處理「把 bytes 變成 (cmd,payload)」並交給 handler。
- AtomicStreamHub 不需要知道資料代表什麼；它只保證「可寫槽位」與「可讀槽位」在跨核心下不撕裂。
- 雙核心任務系統不需要知道業務；它只保證任務生命周期與 affinity 調度。

## 其他文件

- 新增指令流程：[guides/add_new_cmd_flow.md](guides/add_new_cmd_flow.md)
- 舊的 TCP 監聽骨架（參考用）：[guides/run_network_server.md](guides/run_network_server.md)
- 全局背景文件（整理版）：[reference/ai_context.md](reference/ai_context.md)
- ConfigManager（整理版）：[reference/config_manager.md](reference/config_manager.md)

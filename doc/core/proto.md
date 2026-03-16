# Proto（NL3 協議封包 + StreamParser）

Proto 定義了 Slave 與 Master 之間的二進位封包格式（NL3），並提供 StreamParser 用於在 byte stream 上做黏包/拆包、SOF 重同步、CRC 驗證。

對應實作：[proto.py](../../slave/lib/proto.py)

## NL3 封包格式

協議常量：
- SOF=b"NL"
- VER=3（CUR_VER）
- CRC16 覆蓋範圍：header[2:] + payload（不含 SOF、不含 CRC 自身）  
  [proto.py](../../slave/lib/proto.py#L27-L60)

Header 格式（小端）：
- HDR_FMT = "<2sBHHH"
- 欄位：SOF(2) / VER(1) / ADDR(2) / CMD(2) / LEN(2)  
  [proto.py](../../slave/lib/proto.py#L33-L36)

## Proto.pack（如何組包）

- Proto.pack(cmd, payload=b"", addr=0xFFFF) 會回傳完整封包 bytes  
  [proto.py](../../slave/lib/proto.py#L52-L60)

實際 handler 回覆通常走：
- 依 schema 先 encode payload → 再 Proto.pack → ctx["send"](pkt)  
  例如 READY 回覆：[stream_actions.py](../../slave/action/stream_actions.py#L90-L93)

## StreamParser（如何解包：黏包/拆包）

StreamParser 的設計前提：底層可能是 TCP（黏包/拆包），也可能是 WS/UDP（一次收一包但仍可能拆片或混入雜訊）。

### feed(data)

- 把新 bytes 附加到內部 buffer  
  [proto.py](../../slave/lib/proto.py#L67-L69)

### pop() 是「生成器」

pop() 不是回傳單一封包，而是 yield 0..N 個封包（直到目前 buffer 解析不出更多為止）：
- [proto.py](../../slave/lib/proto.py#L70-L102)

因此使用端必須用 for 把它跑完：
- App.handle_stream 會做 for ver,addr,cmd,payload in parser.pop()  
  [app.py](../../slave/app.py#L41-L46)

### pop() 的解析策略（重點行為）

- SOF 重同步：找不到 SOF 就清空 buffer；找到但不在 0 就丟棄前段  
  [proto.py](../../slave/lib/proto.py#L73-L79)
- VER / MAX_LEN 保護：ver 不符或 LEN 過大就丟 1 byte 重新同步  
  [proto.py](../../slave/lib/proto.py#L86-L88)
- CRC 驗證：CRC 正確才 yield 封包，否則丟 1 byte 再同步  
  [proto.py](../../slave/lib/proto.py#L97-L102)

## Proto 與 Schema/Dispatcher 的關係（責任邊界）

Proto 只做到把 bytes 變成 (cmd, payload)：
- cmd 是 uint16
- payload 是原始 bytes

接下來由 Schema/Dispatcher 完成「語意層」：
- SchemaStore 載入 /schema/*.json：cmd_id → cmd_def  
  [schema_loader.py](../../slave/lib/schema_loader.py)
- Dispatcher 依 cmd_def decode payload → 呼叫 handler(ctx,args)  
  [dispatch.py](../../slave/lib/dispatch.py)

這個分層使得：
- 協議封包（Proto）穩定，不因業務變動頻繁修改
- 指令語意（Schema + action handlers）可以快速擴充

## 與 NetBus / DualCore 的接線點

- NetBus.poll() 取到 data 後會呼叫 App.handle_stream，把資料餵進 parser.feed + parser.pop  
  [net_bus.py](../../slave/lib/net_bus.py#L119-L126) → [app.py](../../slave/app.py#L28-L46)
- 這個路徑是 non-blocking 的：符合 DualCore runner 的 loop 模型。

## Server 端對應（概念）

Server 端會用同樣的 NL3 封包格式 pack/unpack，並把 bytes_data 下發到 WS：
- [protocol.py](../../server/core/protocol.py)
- [bus_manager.py](../../server/core/bus_manager.py)

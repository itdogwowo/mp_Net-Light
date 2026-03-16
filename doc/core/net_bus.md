# NetBus（net_bus）

NetBus 是 Slave 端的「統一傳輸層」：把 TCP / WebSocket / UDP 用同一個介面封裝，並用非阻塞 poll 模式把收到的 bytes 交給 App/Proto 解析分發。

對應實作：[net_bus.py](../../slave/lib/net_bus.py)

## NetBus 解決什麼問題

- 讓上層（NetworkTask / App）不需要關心底層 transport 差異：UDP 用 sendto/recvfrom、WS 需要解幀/封幀、TCP 是純 byte stream。
- 讓每個通道「解析狀態隔離」：每個 NetBus instance 都有自己獨立的 StreamParser，避免多條通道共用 parser 造成黏包狀態互相污染  
  [net_bus.py](../../slave/lib/net_bus.py#L23-L29)

## 你應該怎麼用（典型用法）

### 1) 建立 NetBus（帶 App 才會自動解析/分發）

- NetBus 需要 App 才能 create_parser / handle_stream：  
  [net_bus.py](../../slave/lib/net_bus.py#L15-L29)

在 NetworkTask 中的實際用法：
- UDP discovery：[network.py](../../slave/tasks/network.py#L22-L24)
- WS control：[network.py](../../slave/tasks/network.py#L24-L27)

### 2) connect()（TCP/WS 連線 / UDP bind）

- UDP：sock = DGRAM，bind('0.0.0.0', port)  
  [net_bus.py](../../slave/lib/net_bus.py#L33-L36)
- TCP/WS：sock = STREAM，connect(host,port)，WS 額外握手後切換為 non-blocking  
  [net_bus.py](../../slave/lib/net_bus.py#L38-L57)

### 3) poll()（必須在 loop 中反覆呼叫）

poll 做三件事：

1. 從 socket 非阻塞 recv（或 recvfrom）吸資料  
   [net_bus.py](../../slave/lib/net_bus.py#L94-L107)
2. 若是 WS，做簡化解幀取出 payload（目前忽略 mask，只取 payload）  
   [net_bus.py](../../slave/lib/net_bus.py#L108-L117)
3. 若有 app+parser，交給 App.handle_stream 解析 NL3 並 dispatch；否則把 data 放進 _buf 供 readinto  
   [net_bus.py](../../slave/lib/net_bus.py#L119-L132)

## send 回覆（write）

NetBus.write 對不同 transport 做對應封裝：

- UDP：sendto 到最後一個來源（poll 時自動更新 target_addr）  
  [net_bus.py](../../slave/lib/net_bus.py#L99-L102) / [net_bus.py](../../slave/lib/net_bus.py#L140-L142)
- WS：用 opcode 0x2（二進位）做簡封裝後 send  
  [net_bus.py](../../slave/lib/net_bus.py#L142-L149)
- TCP：直接 send  
  [net_bus.py](../../slave/lib/net_bus.py#L149-L150)

上層要回覆封包時，通常走：
- handler 取得 ctx["send"]（NetBus.poll 會把 send_func 傳進 App.handle_stream）  
  [app.py](../../slave/app.py#L34-L38)
- 再用 Proto.pack 組包送回  
  [proto.py](../../slave/lib/proto.py#L52-L60)

## 與其他模組的邊界

- NetBus 不認識「CMD 語意」：它只把 bytes 交給 App（Proto/Schema/Dispatcher）。
- NetBus 不認識「影格/LED」：影格通道由 AtomicStreamHub 管，NetBus 只是控制/資料載入的入口之一。
- NetBus 需要遵守 DualCore 的 non-blocking 要求：connect 後 settimeout(0)，poll 不能卡住 runner。

## 常見注意事項

- WS 解幀目前只處理最簡單情況（忽略 mask，只取 payload），若未來要支援瀏覽器端 masked frame，需要擴充解幀邏輯。
- poll 的 recv_size 會用 bus.shared["Buffer"]["size"]，與整體 Buffer 統一配置一致  
  [net_bus.py](../../slave/lib/net_bus.py#L98-L103)

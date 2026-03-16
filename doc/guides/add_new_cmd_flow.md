# 新增 CMD 指令流程（目前架構）

本文件描述在 mp_Net-Light（Slave 端：/lib + /action + /schema + app.py）中新增一個新指令的標準流程。

## 相關分層（與新增 CMD 的關係）

- /schema/*.json：描述 cmd 的 payload 格式（schema-driven decode/encode）
- /lib/schema_loader.py：載入 /schema，形成 cmd_int → cmd_def  
  [schema_loader.py](../../slave/lib/schema_loader.py)
- /lib/schema_codec.py：依 cmd_def 解碼/編碼 payload bytes
- /lib/dispatch.py：cmd → decode → handler(ctx,args)
- /action/*.py：具體指令行為（handler）
- app.py：裝配層，呼叫 /action/registry.py 註冊所有 handlers  
  [app.py](../../slave/app.py)

## 新增 CMD 的四個步驟

### Step 1：決定 CMD 編號與歸類

建議以 16-bit 區段分域（只是建議，不強制）：
- 0x10xx：sys / discovery / control
- 0x11xx：status / config
- 0x12xx：heartbeat / fs（依專案現況調整）
- 0x20xx：file
- 0x30xx：stream / light

### Step 2：在對應的 schema 檔新增 cmd 定義

例如新增 status 指令，就改 /slave/schema/status.json。

範例（payload 有 2 個欄位）：

```json
{
  "cmd": "0x1101",
  "name": "STATUS_GET",
  "payload": [
    {"name": "flags", "type": "u16"},
    {"name": "detail", "type": "u8"}
  ]
}
```

可用 type 以 /lib/schema_codec.py 支援為準：
- u8/u16/u32/i16/i32
- str_u16len
- bytes_fixed(len)
- bytes_rest

### Step 3：在 /action 新增 handler（或加入既有 action 模組）

把指令行為加到對應分類的 action 檔中：
- sys → /slave/action/sys_actions.py
- status → /slave/action/status_actions.py
- fs → /slave/action/fs_actions.py
- file → /slave/action/file_actions.py
- stream → /slave/action/stream_actions.py

handler 的函數簽名固定為：

```python
def on_xxx(ctx, args):
    pass
```

其中：
- ctx：runtime context（transport、send 函數、peer、外部依賴）
- args：dict，由 schema 解碼而來

### Step 4：在 register(app) 中註冊 cmd → handler

在同一個 action 檔（或 registry）加入：

```python
from lib.schema_loader import cmd_str_to_int

CMD_STATUS_GET = cmd_str_to_int("0x1101")
app.disp.on(CMD_STATUS_GET, on_status_get)
```

註冊入口位於：
- /slave/action/registry.py（register_all）  
  [registry.py](../../slave/action/registry.py)

## 驗證方式

### A) 最快：用 NetBusMaster/PC 工具發送

- tools/NetBusMaster.py 已能用相同協議組包並透過 WS/UDP 下發  
  [NetBusMaster.py](../../tools/NetBusMaster.py)

### B) 離線：直接餵 App.handle_stream

把封包 bytes 丟給 App.handle_stream（或你自己的 parser.feed/pop）即可走完整 decode → dispatch → handler 路徑：
- [app.py](../../slave/app.py#L28-L46)

## 常見錯誤

- schema JSON 不是合法 JSON（空檔、尾逗號、註解）：SchemaStore.load_dir 會失敗
- schema 裡有 cmd，但 handler 沒註冊：dispatch 找不到對應行為
- handler 有回覆需求但 ctx["send"] 是 None：確認 NetBus.poll 有傳 send_func

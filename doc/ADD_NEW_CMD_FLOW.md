# ADD_NEW_CMD_FLOW.md — 新增 CMD 指令的流程（目前架構）

本文件描述在 mp_Net-Light（目前架構：/lib + /action + /schema + app.py）中新增一個新指令的標準流程。

---

## 0) 目前架構回顧（跟新增 CMD 相關）
- `/schema/*.json`：描述 cmd 的 payload 格式（schema-driven decode/encode）
- `/lib/schema_loader.py`：載入 `/schema` 形成 `cmd_int -> cmd_def`
- `/lib/schema_codec.py`：依 cmd_def 解碼/編碼 payload bytes
- `/lib/dispatch.py`：`cmd -> decode -> handler(ctx,args)`
- `/action/*.py`：具體指令行為（handler）
- `app.py`：裝配層，呼叫 `/action/registry.py` 註冊所有 handlers

---

## 1) 新增 CMD 的 4 個步驟（最標準流程）

### Step 1：決定 CMD 編號與歸類
建議用 16-bit 區段分域（只是建議，不強制）：
- 0x10xx：sys
- 0x11xx：status
- 0x12xx：fs
- 0x20xx：file
- 0x30xx：stream/light

例：新增一個 `STATUS_GET`，用 `0x1101`

---

### Step 2：在對應的 schema 檔新增 cmd 定義
例如新增 status 指令，就改 `/schema/status.json`

範例（新增一個 payload 有 2 個欄位的 cmd）：

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

可用 type 以 `/lib/schema_codec.py` 支援為準：
- u8/u16/u32/i16/i32
- str_u16len
- bytes_fixed(len)
- bytes_rest

> 若 schema 檔是空的，至少要是合法 JSON（不能是空字串）。

---

### Step 3：在 /action 新增 handler（或加入既有 action 模組）
在對應分類的 action 檔加入 handler：
- sys → `/action/sys_actions.py`
- status → `/action/status_actions.py`
- fs → `/action/fs_actions.py`
- file → `/action/file_actions.py`
- stream → `/action/stream_actions.py`

handler 的函數簽名固定為：

```python
def on_xxx(ctx, args):
    # ctx: runtime context（可放 send 函數、peer、transport 等）
    # args: dict，由 schema 解碼而來（不再手動 unpack bytes）
    pass
```

---

### Step 4：在 action 的 register(app) 中註冊 cmd
在同一個 action 檔（或 registry 檔）加入：

```python
from lib.schema_loader import cmd_str_to_int

CMD_STATUS_GET = cmd_str_to_int("0x1101")
app.disp.on(CMD_STATUS_GET, on_status_get)
```

> 註冊行為建議放在 `/action/<group>_actions.py` 的 `register(app)` 內。  
> `app.py` 不應隨 cmd 增加而變亂。

---

## 2) 新增完如何驗證？
### A) 離線 loopback 測試（最快）
在 `main.py` 或你自己的測試腳本：
1) 用 `encode_payload(cmd_def, obj)` 建 payload
2) 用 `pack_packet(cmd, payload)` 組包
3) 丟給 `app.on_rx_bytes(pkt)`

### B) 網路測試（真實接收）
啟動 `main.py` 的 TCP server（見 RUN_NETWORK_SERVER.md），用 server 端發送封包即可測。

---

## 3) 常見錯誤
- `syntax error in JSON`：schema 檔是空的、或有尾逗號、或有註解
- `schema 未找到 cmd`：schema 未載入 /schema、或 cmd 寫錯（hex 字串）
- handler 沒被呼叫：忘了 `app.disp.on(cmd, handler)` 註冊

---
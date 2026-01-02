# AI_CONTEXT.md — mp_Net-Light（協議/現況/擴展基礎說明）

> 用途：下次找 AI/工程師擴展功能時，直接貼這份文件即可快速對齊背景與約束，避免重複說明。

---

## 0) 專案概述
mp_Net-Light 是一個 Server ⇄ MicroPython Client（ESP 系列 MCU）之間的控制、檔案傳輸、燈效串流系統。

設計目標：
- 二進位、低成本、可擴展
- 同一套協議可用於 TCP/UDP/UART/檔案/loopback
- MCU 單核心：避免阻塞、避免大量配置造成 GC 抖動
- 以 schema（JSON）驅動 payload 解碼/編碼（避免硬編碼 bytes offset）

---

## 1) 通道與工程分層（現況）
### 1.1 通道
- TCP：控制/狀態/檔案傳輸（可靠，會黏包/拆包，需要 stream parser）
- UDP：燈效 streaming（低延遲，可丟包；尚未實作正式 streaming payload）

### 1.2 工程分層
- `/lib`：穩定底座（協議、parser、schema loader、dispatcher、file_rx 等），不常改
- `/action`：行為層（接收 cmd 後做什麼），常改、常新增
- `/schema`：cmd/payload schema JSON 分檔（按大類拆分）
- `app.py`（根目錄）：裝配層（載入 schema、建立 dispatcher、註冊 action）
- `main.py`：測試/入口（可離線 loopback 自測）

---

## 2) 二進位封包協議（已定稿）
### 2.1 封包格式（VER=3）
```
SOF(2)  VER(1)  ADDR(2)  CMD(2)  LEN(2)  DATA(LEN)  CRC16(2)
```

- SOF：固定 `b"NL"`
- VER：固定 `3`
- ADDR：uint16 little-endian（外層目的地址；目前離線/loopback 常用，不強制依賴）
- CMD：uint16 little-endian
- LEN：uint16 little-endian（單包 DATA 長度）
- CRC16：CRC16-CCITT-FALSE（poly=0x1021, init=0xFFFF）
  - CRC 覆蓋範圍：`VER..DATA`（不含 SOF）
  - 目前已採用 256-entry lookup table 加速版

### 2.2 解析策略
- 必須完整收齊一幀（HDR+DATA+CRC）
- 驗 CRC
- 再交給上層 dispatch（不在 CRC 前做過多快篩）

### 2.3 max_len
- `LEN(2)` 是對端宣告單包 payload 長度
- `max_len` 是 parser 本地安全上限，避免誤同步讀到超大 LEN 造成等待巨包/爆 RAM

---

## 3) Schema 驅動 payload 解碼/編碼（現況）
### 3.1 schema 分檔（避免單一巨型 proto_map.json）
- `/schema/sys.json`
- `/schema/status.json`
- `/schema/file.json`
- `/schema/fs.json`
- `/schema/stream.json`

每個 schema 檔案格式：
```json
{
  "group": "file",
  "cmds": [
    {"cmd":"0x2001","name":"FILE_BEGIN","payload":[...]}
  ]
}
```

### 3.2 解碼/編碼規則
- 不再強制「所有 cmd 的 DATA 都以 dst_addr(u16) 開頭」
- payload 格式完全由 schema 描述決定
- `bytes_rest` type 用於「吃掉剩餘 bytes」（例如 FILE_CHUNK.data）

---

## 4) 已完成模組（MCU）
### 4.1 `/lib/proto.py`
- `pack_packet(cmd, payload, addr, ver=3)`
- `StreamParser.feed()/pop()`：TCP/UART 用流式解包（黏包/拆包 + SOF resync）
- CRC16 table 加速版

### 4.2 `/lib/schema_loader.py`
- `SchemaStore.load_dir("/schema")`：載入多份 JSON schema
- 建立 `cmd_int -> cmd_def` map
- 空檔會略過；JSON parse error 會印出檔名/片段方便 debug

### 4.3 `/lib/schema_codec.py`
- `decode_payload(cmd_def, payload_bytes) -> dict`
- `encode_payload(cmd_def, dict) -> bytes`
- 支援 types：
  - u8/u16/u32/i16/i32
  - str_u16len
  - bytes_fixed(len)
  - bytes_rest

### 4.4 `/lib/dispatch.py`
- `Dispatcher.dispatch(cmd_int, payload_bytes, ctx)`：
  - 用 schema 解碼成 args dict
  - 根據 cmd_int 找 handler 執行

### 4.5 檔案傳輸（已可用）
- FILE 三件套（接收端）：
  - FILE_BEGIN / FILE_CHUNK / FILE_END
  - seek 寫入 + SHA256 驗證（串流計算）
- 目前離線 loopback 已驗證成功（131072 bytes 可正確重組）

### 4.6 FS（目錄樹/快照）
- FS_TREE_GET：單包回傳 tree 文字（方便快速看）
- FS_SNAP_GET：生成漂亮格式化 JSON snapshot -> 以 FILE 三件套回傳（避免單包限制）
- 目前 snapshot 格式：人眼友善 JSON（可讀性優先）

---

## 5) /action（行為層）現況
- `/action/file_actions.py`：註冊 file 類 cmd，呼叫 `app.file_rx`
- `/action/fs_actions.py`：註冊 FS_TREE_GET、FS_SNAP_GET
- `/action/registry.py`：`register_all(app)` 統一註冊入口

---

## 6) main.py（離線自測）現況
可在無網路下自測：
1) 顯示系統資訊（uid、uname、mem、fs total/free）
2) FS_TREE_GET 顯示完整樹
3) FS_SNAP_GET 生成 `/fs_snapshot.json` 並以 FILE 三件套回傳到 `/rx_snapshot.json`，main 會印出其內容（前 N 字元）
4) FILE 三件套 loopback 上傳/下載測試並 sha256 驗證

---

## 7) 待完成項目（下一步擴展）
### 7.1 STATUS（狀態指令）
- 定義 STATUS_GET / STATUS_RSP schema
- 將 MCU standing/state 以固定格式或 KV 格式回傳（目前 main 直接 print）

### 7.2 UDP streaming（燈效）
- 定義 STREAM_OPEN/FRAME/CLOSE schema
- FRAME payload 建議：frame_id + raw bytes（可能需要分片）
- 低延遲優先、允許丟包；可靠傳輸走 TCP + file/chunk

### 7.3 真實總線接入
- 將 `ctx["send_loopback"]` 替換為 socket/UART send
- TCP 接收：feed StreamParser
- UDP：parse_one 或同樣 feed/pop（datagram 不黏包）

---

## 8) 擴展時必須遵守的約束
1) 封包 header 不隨意改（除非升 VER）
2) payload 格式由 schema 控制，避免散落硬編碼 bytes offset
3) MCU 單核心：避免大 RAM 配置、避免阻塞
4) 大資料走「檔案三件套」或 snapshot（避免單包限制）
5) schema JSON 分檔管理（/schema），避免單一超大檔

---

## 9) 詢問 AI 的模板（可直接貼）
> 我在做 mp_Net-Light。封包協議固定為：
> SOF(2)=b'NL', VER(1)=3, ADDR(2), CMD(2), LEN(2), DATA, CRC16(2)，CRC16-CCITT-FALSE 覆蓋 VER..DATA（不含 SOF），CRC16 table 版已完成。
> MCU 端工程分層：/lib（穩定底座）、/action（行為層）、/schema（cmd schema JSON 分檔）、app.py（裝配註冊）、main.py（離線自測）。
> payload 解碼/編碼由 /schema/*.json 描述，使用 lib/schema_codec.py 通用解析，不再硬編碼 bytes offset。
> 我現在要新增功能：{描述新增 cmd 或 streaming 或 status}。
> 請遵守現有協議與分層方式，提供需要新增/修改的檔案內容（可直接覆蓋）與簡短說明。

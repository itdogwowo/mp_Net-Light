# AI_CONTEXT.md — mp_Net-Light 統一專案說明文件

> **用途**：AI/工程師快速對齊專案背景、架構演進、擴展約束的唯一真相來源  
> **最後更新**：2024-XX-XX（整合雙核心架構 + Schema驅動協議）

---

## 📋 目錄

1. [專案概述](#1-專案概述)
2. [系統架構演進](#2-系統架構演進)
3. [二進位封包協議](#3-二進位封包協議)
4. [三級數據總線 (SysBus)](#4-三級數據總線-sysbus)
5. [雙核心分工與同步機制](#5-雙核心分工與同步機制)
6. [Schema 驅動 Payload 系統](#6-schema-驅動-payload-系統)
7. [工程分層與模組現況](#7-工程分層與模組現況)
8. [指令集現況](#8-指令集現況)
9. [關鍵技術實現](#9-關鍵技術實現)
10. [擴展約束與最佳實踐](#10-擴展約束與最佳實踐)
11. [詢問 AI 的標準模板](#11-詢問-ai-的標準模板)

---

## 1) 專案概述

**mp_Net-Light** 是一個高效能 **Server ⇄ MicroPython Client**（ESP32 系列 MCU）傳輸控制系統。

### 核心演進路徑
```
[單核阻塞模式] 
    ↓
[TCP/UDP 雙通道協議標準化] 
    ↓
[Schema 驅動 Payload 解析] 
    ↓
[雙核心異步架構] ← 當前版本
```

### 設計目標
- ✅ **二進位協議**：低延遲、低功耗、可靠傳輸
- ✅ **多通道統一**：同一套協議支援 TCP/UDP/UART/檔案/loopback
- ✅ **Schema 驅動**：避免硬編碼 bytes offset，協議可擴展
- ✅ **雙核心架構**：支援 2000+ 顆 LED 高頻刷新（Core 1）同時保持網路穩定（Core 0）
- ✅ **零拷貝思維**：`memoryview` + 指針交換技術減少記憶體抖動

---

## 2) 系統架構演進

### 2.1 第一階段：單核阻塞模式
```
[TCP接收] → [解析] → [執行] → [LED渲染] → [回到接收]
              ↑__________________________|
                   (阻塞等待)
```
**痛點**：LED 渲染時網路斷線、大量 LED 時 GC 抖動

---

### 2.2 第二階段：Schema 驅動協議標準化
```
[Stream Parser] → [Schema Decoder] → [Dispatcher] → [Action Layer]
     ↑                                                    ↓
     |_____________ [CRC16 驗證 + SOF 重同步] ____________|
```
**成果**：
- 協議與業務邏輯解耦
- 支援離線 loopback 自測
- 檔案傳輸三件套（BEGIN/CHUNK/END + SHA256）

---

### 2.3 第三階段：雙核心異步架構（當前）
```
┌─────────────────────────────────────────────────────────┐
│                      Core 0 (Network)                   │
│  [TCP/UDP/WS] → [NetBus(IO)] → [RX Hub]                │
└──────────────────────────┬──────────────────────────────┘
                           │ SysBus (Services/Providers)
                           │ AtomicStreamHub (三緩衝狀態機)
┌──────────────────────────┴──────────────────────────────┐
│                Core 0 (Decode Task) / 可拆 Core 1        │
│  [bus_decode] → [StreamParser] → [Schema Decode] → [Dispatcher] → [Actions] │
│                     │                                      │
│                     └──────────────→ [pixel_stream Hub] ───┘
└─────────────────────────────────────────────────────────┘
```

---

## 3) 二進位封包協議

### 3.1 封包格式（VER=4，CRC32）
```
┌───────┬───────┬────────┬────────┬────────┬──────────┬──────────┐
│  SOF  │  VER  │  ADDR  │  CMD   │  LEN   │   DATA   │  CRC32   │
│ (2B)  │ (1B)  │  (2B)  │  (2B)  │  (2B)  │ (LEN B)  │   (4B)   │
└───────┴───────┴────────┴────────┴────────┴──────────┴──────────┘
```

### 3.2 欄位說明
| 欄位   | 長度 | 說明                                      |
|--------|------|-------------------------------------------|
| SOF    | 2B   | 固定 `b"NL"` (0x4E4C)                     |
| VER    | 1B   | 協議版本，固定 `4`                        |
| ADDR   | 2B   | 目的地址 (uint16 LE，loopback 可忽略)     |
| CMD    | 2B   | 指令碼 (uint16 LE)，由 Schema 定義        |
| LEN    | 2B   | DATA 長度 (uint16 LE)                     |
| DATA   | 變長 | Payload，格式由 `/schema/*.json` 定義    |
| CRC32  | 4B   | CRC32（覆蓋範圍見下）                    |

### 3.3 CRC 計算範圍
```
CRC32 覆蓋範圍 = VER + ADDR + CMD + LEN + DATA
               （不含 SOF，不含 CRC32 自身）
```

### 3.4 解析策略
1. **流式解析**：`StreamParser.feed(bytes)` + `pop()` 處理 TCP 黏包/拆包
2. **SOF 重同步**：錯位時自動掃描下一個 `b"NL"` 標記
3. **CRC 驗證優先**：完整收齊一幀後先驗 CRC，再 dispatch
4. **max_len 保護**：避免誤同步讀到超大 LEN 造成記憶體溢出

---

## 4) 三級數據總線 (SysBus)

為實現模組解耦與雙核安全，引入 **`lib/sys_bus.py`** 作為中樞神經系統。

### 4.1 三級存儲空間
```python
from lib.sys_bus import bus

# ─── 1. Services：核心間/模組間共享大型對象 ───
hub = AtomicStreamHub(size_bytes, num_buffers=3)
bus.register_service("pixel_stream", hub)
hub = bus.get_service("pixel_stream")

# ─── 2. Providers：動態資訊回報（解耦依賴）───
bus.register_provider("fps", lambda: led_driver.get_fps())
bus.register_provider("ram_free", lambda: gc.mem_free())

# ─── 3. Shared：App 間讀寫同步 ───
bus.shared["brightness"] = 128
bus.shared["power"] = True
```

### 4.2 設計哲學
| 級別      | 用途                     | 特性                          |
|-----------|--------------------------|-------------------------------|
| Services  | 單例服務（Buffer/驅動）  | 註冊一次，全局訪問            |
| Providers | 健康度回報               | Lambda 延遲計算，避免循環導入 |
| Shared    | 狀態同步                 | 簡單 dict，輕量級             |

---

## 5) 雙核心分工與同步機制

### 5.1 職責劃分
| 核心    | 負責模組                              | 角色          |
|---------|---------------------------------------|---------------|
| Core 0  | TCP/UDP 解析、Dispatcher、檔案寫入   | Buffer 生產者 |
| Core 1  | APA102/WS2812 驅動、本地特效運算     | Buffer 消費者 |

### 5.2 啟動流程
```python
# main.py
import _thread
from rendering_task import rendering_task

# Core 0 初始化
app = create_app()
app.start()

# Core 1 啟動渲染任務
_thread.start_new_thread(rendering_task, ())
```

### 5.3 雙核通訊規範
✅ **允許**：
- Core 0 寫入 `SysBus.services["pixel_stream"]` 的寫緩衝
- Core 1 讀取讀緩衝並檢查 `hub.dirty`

❌ **禁止**：
- 兩核心同時修改同一個 `dict` key
- Core 1 主動修改網路相關狀態

---

## 6) Schema 驅動 Payload 系統

### 6.1 Schema 分檔策略
避免單一巨型 `proto_map.json`，按功能模組拆分：
```
/schema/
  ├── sys.json       # 系統級指令
  ├── status.json    # 狀態查詢/回報
  ├── file.json      # 檔案傳輸三件套
  ├── fs.json        # 檔案系統快照
  └── stream.json    # LED 串流
```

### 6.2 Schema 格式範例
```json
{
  "group": "stream",
  "cmds": [
    {
      "cmd": "0x3001",
      "name": "STREAM_FRAME",
      "payload": [
        {"name": "frame_id", "type": "u32"},
        {"name": "offset", "type": "u16"},
        {"name": "pixels", "type": "bytes_rest"}
      ]
    }
  ]
}
```

### 6.3 支援的 Payload 類型
| 類型          | 說明                          | 範例用途              |
|---------------|-------------------------------|-----------------------|
| u8/u16/u32    | 無符號整數                    | 計數器、ID            |
| i16/i32       | 有符號整數                    | 溫度、偏移量          |
| str_u16len    | 字串（前綴 2B 長度）          | 檔案名、路徑          |
| bytes_fixed   | 固定長度 bytes                | SHA256 (32B)          |
| bytes_rest    | 吃掉剩餘所有 bytes            | 檔案塊、像素資料      |

---

## 7) 工程分層與模組現況

### 7.1 目錄結構
```
/
├── lib/                    # 底座層（穩定，少改）
│   ├── proto.py            # 封包打包/解析
│   ├── schema_loader.py    # Schema JSON 加載器
│   ├── schema_codec.py     # Payload 編解碼引擎
│   ├── dispatch.py         # 指令分發器
│   ├── sys_bus.py          # ★ 三級數據總線
│   ├── buffer_hub.py       # ★ 三緩衝狀態機
│   ├── task_manager.py     # ★ 任務註冊/親和性/Runner
│   ├── fs_manager.py       # ★ 檔案系統管理
│   ├── net_bus.py          # 網路接收/解析
│   ├── network_manager.py  # 網路介面管理
│   ├── LEDController.py    # LED 控制器 (WS2812/APA102/PCA9685)
│   ├── apa102.py           # APA102 驅動
│   ├── pca9685.py          # PCA9685 PWM 驅動
│   ├── ESP_Boot.py         # 啟動/硬體初始化
│   └── ConfigManager.py    # 設定檔管理
│
├── action/                 # 行為層（常改）
│   ├── registry.py         # 統一註冊入口
│   ├── file_actions.py     # 檔案傳輸指令
│   ├── fs_actions.py       # 檔案系統指令
│   ├── stream_actions.py   # ★ LED 串流指令
│   ├── status_actions.py   # ★ 狀態回報指令
│   ├── heartbeat_actions.py# 心跳指令
│   └── sys_actions.py      # 系統指令
│
├── tasks/                  # 任務層（Core 0/1 Runner 調度）
│   ├── network.py
│   ├── render.py
│   └── web_ui.py
│
├── schema/                 # 協議定義
│   ├── sys.json
│   ├── status.json
│   ├── file.json
│   ├── fs.json
│   ├── stream.json
│   └── heartbeat.json
│
├── app.py                  # 裝配層
├── boot.py                 # 硬體與服務初始化
└── main.py                 # 測試/入口
```

### 7.2 關鍵模組說明

#### `/lib/proto.py`
- `pack_packet(cmd, payload, addr=0, ver=3) -> bytes`
- `StreamParser.feed(data)` / `.pop() -> (cmd, payload, addr)`
- CRC16 256-entry lookup table 加速版

#### `/lib/schema_loader.py`
```python
store = SchemaStore()
store.load_dir("/schema")
cmd_def = store.get_cmd(0x3001)  # STREAM_FRAME
```

#### `/lib/schema_codec.py`
```python
args = decode_payload(cmd_def, payload_bytes)  # -> dict
payload = encode_payload(cmd_def, args)        # -> bytes
```

#### `/lib/buffer_hub.py`
```python
hub = AtomicStreamHub(size_bytes, num_buffers=3)

# Core 0
view = hub.get_write_view()
if view is not None:
    view[0] = 255
    view[1] = 0
    view[2] = 0
    hub.commit()

# Core 1
view = hub.get_read_view()
if view is not None:
    spi.write(view)
```

---

好的!我來幫你完整整理並更新指令集章節。我發現了一些問題需要修正:

## 8) 指令集現況(完整版)

### 8.0 指令碼分配規劃

```
0x10xx - 系統發現與控制 (sys.json)
0x11xx - 狀態查詢與配置 (status.json)
0x12xx - 心跳與檔案系統 (heartbeat.json, fs.json)
0x20xx - 檔案傳輸 (file.json)
0x30xx - LED 串流 (stream.json)
```

---

### 8.1 系統發現指令 (0x10xx - sys.json)

| CMD    | 名稱             | 方向          | Payload                                                  | 說明                     |
|--------|------------------|---------------|----------------------------------------------------------|--------------------------|
| 0x1001 | DISCOVER         | Server → MCU  | `server_ip(str)` `ws_url(str)`                          | UDP 廣播發現從機         |
| 0x1002 | SLAVE_ANNOUNCE   | MCU → Server  | `slave_id(str)` `pixel_count(u16)` `hw_version(str)`   | 從機回報身份與硬體資訊   |

#### 典型流程
```
Server (UDP 廣播) 
  → DISCOVER("192.168.1.100", "ws://192.168.1.100:8080")
    ← SLAVE_ANNOUNCE("ESP32_A1B2C3", 2048, "v2.1")
Server 記錄從機資訊 → 建立 TCP 連線
```

---

### 8.2 狀態查詢指令 (0x11xx - status.json)

| CMD    | 名稱               | 方向          | Payload                              | 說明                        |
|--------|-------------------|---------------|--------------------------------------|----------------------------|
| 0x1101 | STATUS_GET        | Server → MCU  | `query_type(u8)`                     | 請求狀態 (0=全部, 1=精簡)   |
| 0x1102 | STATUS_RSP        | MCU → Server  | `status_json(str)`                   | 回傳 JSON 格式狀態          |
| 0x1103 | STATUS_UPDATE     | Server → MCU  | `config_json(str)`                   | 更新配置 (亮度/模式等)      |
| 0x1104 | STATUS_UPDATE_ACK | MCU → Server  | `success(u8)` `message(str)`         | 配置更新結果回報            |

#### query_type 定義
```python
QUERY_TYPE_FULL = 0     # 完整狀態 (含 Providers 所有資訊)
QUERY_TYPE_BRIEF = 1    # 精簡狀態 (僅關鍵指標)
```

#### STATUS_RSP JSON 格式範例
```json
{
  "uptime_ms": 123456,
  "mem_free": 45120,
  "fps": 60,
  "led_power": true,
  "brightness": 128,
  "mode": "stream"
}
```

---

### 8.3 心跳指令 (0x12xx - heartbeat.json)

| CMD    | 名稱              | 方向          | Payload                                                              | 說明              |
|--------|-------------------|---------------|----------------------------------------------------------------------|-------------------|
| 0x1201 | HEARTBEAT         | MCU → Server  | `slave_id(str)` `uptime_ms(u32)` `mem_free(u32)` `ws_connected(u8)` | 從機主動心跳      |
| 0x1202 | HEARTBEAT_ACK     | Server → MCU  | `server_time(u32)` `success(u8)`                                     | Server 確認存活   |

#### 設計說明
- **心跳週期**: 建議 5-10 秒 (可配置)
- **超時判定**: Server 端 30 秒無心跳視為離線
- **時鐘同步**: `server_time` 用於簡易 NTP 同步 (ms 級精度)

---

### 8.4 檔案系統指令 (0x12xx - fs.json)

| CMD    | 名稱          | 方向          | Payload                                                              | 說明                        |
|--------|---------------|---------------|----------------------------------------------------------------------|----------------------------|
| 0x1205 | FS_TREE_GET   | Server → MCU  | `path(str)` `max_depth(u8)` `include_size(u8)`                      | 請求目錄樹 (單包回傳)       |
| 0x1206 | FS_TREE_RSP   | MCU → Server  | `path(str)` `tree(str)`                                              | 回傳文字格式目錄樹          |
| 0x1213 | FS_SNAP_GET   | Server → MCU  | `path(str)` `out_path(str)` `max_depth(u8)` `include_size(u8)`     | 生成 JSON 快照 (FILE 傳輸)  |

#### FS_TREE_RSP 格式範例
```
/
├── lib/ (4 files)
│   ├── proto.py (3.2KB)
│   └── sys_bus.py (1.8KB)
├── schema/ (6 files)
└── main.py (5.4KB)
```

#### FS_SNAP_GET 流程
```
Server → FS_SNAP_GET("/", "/snapshot.json", max_depth=5)
MCU    → 生成 JSON 快照 → 觸發 FILE_BEGIN/CHUNK/END 回傳
Server ← 接收完整 JSON 檔案
```

---

### 8.5 檔案傳輸指令 (0x20xx - file.json)

| CMD    | 名稱       | 方向          | Payload                                                              | 說明                  |
|--------|-----------|---------------|----------------------------------------------------------------------|----------------------|
| 0x2001 | FILE_BEGIN | 雙向          | `file_id(u16)` `total_size(u32)` `chunk_size(u16)` `sha256(32B)` `path(str)` | 開始檔案傳輸 |
| 0x2002 | FILE_CHUNK | 雙向          | `file_id(u16)` `offset(u32)` `data(bytes_rest)`                     | 傳輸檔案塊            |
| 0x2003 | FILE_END   | 雙向          | `file_id(u16)`                                                       | 傳輸完成通知          |
| 0x2004 | FILE_ACK   | 雙向          | `file_id(u16)` `offset(u32)`                                         | 確認收到 (用於斷點續傳) |

#### 傳輸流程圖
```
發送端                                     接收端
  │                                          │
  ├─ FILE_BEGIN ──────────────────────────→ │ (建立檔案, 初始化 SHA256)
  │                                          │
  ├─ FILE_CHUNK (offset=0) ───────────────→ │ (寫入 + 更新 SHA256)
  │  ←─────────────────────────── FILE_ACK  │ (確認收到)
  │                                          │
  ├─ FILE_CHUNK (offset=512) ──────────────→ │
  │  ←─────────────────────────── FILE_ACK  │
  │                                          │
  ├─ FILE_END ─────────────────────────────→ │ (驗證 SHA256)
  │  ←─────────────────────────── FILE_ACK  │ (成功/失敗)
```

#### file_id 用途
- 支援多檔案並行傳輸 (不同 file_id)
- 範圍: 0x0001 - 0xFFFE (0x0000/0xFFFF 保留)

#### chunk_size 建議值
```python
TCP:  1024 - 4096 bytes  # 穩定優先
UDP:  512 - 1024 bytes   # 避免 IP 分片
```

---

### 8.6 LED 串流指令 (0x30xx - stream.json)

| CMD    | 名稱          | 方向          | Payload                                  | 說明              |
|--------|---------------|---------------|------------------------------------------|-------------------|
| 0x3001 | STREAM_START  | Server → MCU  | `fps(u8)`                                | 開始串流模式      |
| 0x3002 | STREAM_STOP   | Server → MCU  | (空)                                     | 停止串流          |
| 0x3003 | STREAM_FRAME  | Server → MCU  | `frame_id(u32)` `pixel_data(bytes_rest)` | 推送像素幀        |

#### 串流流程
```
Server → STREAM_START(fps=60)
MCU    → 切換到串流模式 (停止本地特效)
       → 啟動 Core 1 高頻渲染

Server → STREAM_FRAME(id=1, pixels=[...])  ─┐
       → STREAM_FRAME(id=2, pixels=[...])   ├─ UDP 推送 (允許丟幀)
       → STREAM_FRAME(id=3, pixels=[...])  ─┘

Server → STREAM_STOP
MCU    → 恢復本地特效模式
```

#### pixel_data 格式
```python
# RGBw8888 格式 (每像素 4 bytes)
pixel_data = bytes([
    R0, G0, B0, W0,  # LED 0
    R1, G1, B1, W0,  # LED 1
    # ...
])

# 對於 2048 顆 LED
len(pixel_data) = 2048 * 4 = 8192 bytes
```

#### 分片策略 (針對大規模 LED)
```python
# 超過 MTU 時建議分片
MAX_PIXELS_PER_FRAME = 1000  # 3KB per packet

# 方案 A: 多包傳輸 (需擴展協議)
STREAM_FRAME_PART(frame_id, part_index, total_parts, data)

# 方案 B: 降低解析度
# Server 端先降採樣再推送
```

---

### 8.7 指令碼衝突檢查

#### ⚠️ 發現的問題
```
0x1201 - HEARTBEAT (heartbeat.json)
0x1205 - FS_TREE_GET (fs.json)
0x1206 - FS_TREE_RSP (fs.json)
0x1213 - FS_SNAP_GET (fs.json)
```
**心跳和檔案系統指令都在 0x12xx 區段,但屬於不同功能模組**

#### 🔧 建議調整方案

**方案 A: 重新規劃指令碼分配**
```
0x10xx - 系統發現與控制 (sys.json)
0x11xx - 狀態查詢與配置 (status.json)
0x12xx - 心跳指令 (heartbeat.json)
0x13xx - 檔案系統 (fs.json)           ← 新增
0x20xx - 檔案傳輸 (file.json)
0x30xx - LED 串流 (stream.json)
```

修改後的 fs.json:
```json
{
  "group": "fs",
  "cmds": [
    {"cmd": "0x1301", "name": "FS_TREE_GET", ...},
    {"cmd": "0x1302", "name": "FS_TREE_RSP", ...},
    {"cmd": "0x1303", "name": "FS_SNAP_GET", ...}
  ]
}
```

**方案 B: 合併心跳到狀態指令 (更簡潔)**
```
0x10xx - 系統發現 (sys.json)
0x11xx - 狀態與心跳 (status.json)    ← 合併 heartbeat
0x12xx - 檔案系統 (fs.json)
0x20xx - 檔案傳輸 (file.json)
0x30xx - LED 串流 (stream.json)
```

**我建議採用方案 A**,因為:
1. 心跳是高頻獨立功能,應該獨立管理
2. 擴展性更好,未來可能新增 0x14xx (韌體升級) 等

---

### 8.8 完整指令索引表

| 指令碼範圍 | 功能模組     | Schema 檔案      | 主要用途                  |
|------------|--------------|------------------|---------------------------|
| 0x10xx     | 系統發現     | sys.json         | UDP 廣播、從機註冊        |
| 0x11xx     | 狀態管理     | status.json      | 狀態查詢、配置更新        |
| 0x12xx     | 心跳         | heartbeat.json   | 保持連線、時鐘同步        |
| 0x13xx     | 檔案系統     | fs.json          | 目錄樹、快照生成          |
| 0x20xx     | 檔案傳輸     | file.json        | 大檔案上傳/下載           |
| 0x30xx     | LED 串流     | stream.json      | 即時像素推送              |


---

## 9) 關鍵技術實現

### 9.1 三緩衝狀態機 (AtomicStreamHub)

#### 核心概念
```
[IDLE]  ← get_write_view() 取得可寫槽位
  ↓ commit()
[READY] ← get_read_view() 取得可讀槽位（並標記 READING）
  ↓ 下一次 get_read_view()/read_into() 時釋放
[IDLE]
```

#### 實作細節
```python
IDLE, READY, READING = 0, 1, 2

class AtomicStreamHub:
    def __init__(self, size, num_buffers=3):
        self._bufs = [bytearray(size) for _ in range(num_buffers)]
        self._views = [memoryview(b) for b in self._bufs]
        self._status = [IDLE] * num_buffers
        self._w_ptr = 0
        self._r_ptr = 0
        self._last_read_idx = None

    @property
    def dirty(self):
        return self._status[self._r_ptr] == READY
```

#### 優勢
✅ **零拷貝**：讀取端直接取得 `memoryview`  
✅ **低 GC 壓力**：啟動時預分配 buffers 與 views  
✅ **可吸收抖動**：預設 3 buffers，降低生產/消費瞬時失配的撕裂風險

---

### 9.2 CRC16 加速版

#### Lookup Table 生成
```python
def _crc16_make_table(poly=0x1021):
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = (crc << 1) ^ poly if crc & 0x8000 else crc << 1
        table.append(crc & 0xFFFF)
    return table

CRC16_TABLE = _crc16_make_table()
```

#### 計算函式
```python
def crc16_ccitt_false(data, init=0xFFFF):
    crc = init
    for b in data:
        crc = ((crc << 8) ^ CRC16_TABLE[(crc >> 8) ^ b]) & 0xFFFF
    return crc
```

#### 性能提升
- **Before**：每 byte 8 次位運算
- **After**：每 byte 1 次查表 + 2 次 XOR
- **速度提升**：~5x（大量封包時明顯）

---

### 9.3 Schema 動態解碼引擎

#### 核心邏輯
```python
def decode_payload(cmd_def, payload):
    args = {}
    offset = 0
    for field in cmd_def["payload"]:
        name = field["name"]
        ftype = field["type"]
        
        if ftype == "u16":
            args[name] = struct.unpack_from("<H", payload, offset)[0]
            offset += 2
        elif ftype == "bytes_rest":
            args[name] = payload[offset:]
            break
        # ... 其他類型
    return args
```

#### 優勢
- 協議變更只需修改 JSON，無需改程式碼
- 自動處理 endianness（統一用 little-endian）
- 支援變長 payload（bytes_rest）

---

### 9.4 檔案傳輸串流 SHA256 驗證

#### 接收器實作
```python
class FileReceiver:
    def begin(self, path, total_size, expected_sha):
        self._sha = hashlib.sha256()
        self._file = open(path, "wb")
    
    def chunk(self, offset, data):
        self._file.seek(offset)
        self._file.write(data)
        self._sha.update(data)  # 串流更新
    
    def end(self):
        self._file.close()
        actual_sha = self._sha.digest()
        return actual_sha == self._expected_sha
```

#### 優勢
- 不需一次性讀取完整檔案到記憶體
- 邊接收邊驗證
- 支援斷點續傳（offset 定址）

---

## 10) 擴展約束與最佳實踐

### 10.1 模組註冊冪等性原則
```python
# ❌ 錯誤：直接 import 時就分配資源
hub = AtomicStreamHub(2048)

# ✅ 正確：在 register 時檢查後註冊
def register(app):
    hub = app.bus.get_service("pixel_stream")
    if hub is None:
        hub = AtomicStreamHub(size_bytes, num_buffers=3)
        app.bus.register_service("pixel_stream", hub)
```

### 10.2 Provider 註冊規範
```python
# action/led_actions.py
def register(app):
    led = LEDDriver()
    
    # 註冊健康度回報
    app.bus.register_provider("led_fps", lambda: led.get_fps())
    app.bus.register_provider("led_power", lambda: led.is_on())
    
    # 註冊指令處理器
    app.dispatcher.register(0x3001, lambda args: led.set_frame(args))
```

### 10.3 雙核數據交換規範

#### ✅ 安全模式
```python
# Core 0（生產者）
view = hub.get_write_view()
if view is not None:
    for i, pixel in enumerate(pixels):
        view[i*3:(i+1)*3] = pixel
    hub.commit()

# Core 1（消費者）
view = hub.get_read_view()
if view is not None:
    spi.write(view)
```

#### ❌ 危險模式
```python
# 兩核心同時寫同一個 list
shared_list.append(data)  # Race condition!
```

### 10.4 記憶體管理最佳實踐

#### 1. 預分配 Buffer
```python
# ✅ 啟動時一次性分配
pixel_buf = bytearray(num_leds * 3)

# ❌ 每次都 new
def render():
    buf = bytearray(num_leds * 3)  # GC 殺手
```

#### 2. 使用 memoryview
```python
# ✅ 零拷貝切片
view = memoryview(pixel_buf)
chunk = view[0:300]  # 不複製

# ❌ 產生新對象
chunk = pixel_buf[0:300]  # 複製 300 bytes
```

#### 3. 定期 GC
```python
import gc
gc.collect()
gc.threshold(gc.mem_free() // 4 + gc.mem_alloc())
```

---

## 11) 詢問 AI 的標準模板

### 模板 A：新增指令
```markdown
我在擴展 mp_Net-Light 專案。

**現有協議**：
- 封包格式：SOF(2)=b'NL' + VER(1)=3 + ADDR(2) + CMD(2) + LEN(2) + DATA + CRC16(2)
- CRC16-CCITT-FALSE (poly=0x1021, init=0xFFFF)，覆蓋 VER..DATA
- Payload 格式由 /schema/*.json 定義，使用 schema_codec.py 解碼

**現有分層**：
- /lib：底座（proto.py, schema_loader.py, dispatch.py, sys_bus.py, buffer_hub.py, task_manager.py）
- /action：行為層（file_actions.py, fs_actions.py, stream_actions.py, status_actions.py, heartbeat_actions.py, sys_actions.py）
- /tasks：任務層（network.py, render.py, web_ui.py）
- /schema：協議定義（sys.json, status.json, heartbeat.json, file.json, fs.json, stream.json）

**我要新增功能**：
{描述新指令：例如「新增 LED 模式切換指令 MODE_SET (0x3010)，payload 包含 mode_id(u8) 和 params(bytes_rest)」}

**需求**：
1. 新增對應的 schema 定義
2. 在 /action 新增處理邏輯
3. 透過 SysBus.register_provider 回報當前模式
4. 遵守「先檢查後註冊」原則

請提供：
- /schema/*.json 新增內容
- /action/*.py 新增檔案或修改內容
- 簡短說明
```

---

### 模板 B：雙核功能擴展
```markdown
我在優化 mp_Net-Light 雙核系統。

**現有架構**：
- Core 0：網路接收、Schema 解碼、Dispatcher 分發
- Core 1：LED 渲染（APA102/WS2812）、本地特效運算
- 數據同步：SysBus (Services/Providers/Shared) + AtomicStreamHub (三緩衝狀態機)

**我要新增功能**：
{描述：例如「新增本地特效引擎，Core 1 在無網路時自動運行呼吸燈，需與串流模式互斥」}

**需求**：
1. 若涉及 Core 間數據交換，請定義新的 Service
2. 避免 Race Condition
3. 透過 Provider 回報特效狀態

請提供：
- 新 Service 定義（如需要）
- tasks/render.py 修改內容
- 狀態回報邏輯
```

---

### 模板 C：性能優化
```markdown
我要優化 mp_Net-Light 的 {模組名稱} 性能。

**當前瓶頸**：
{描述：例如「FILE_CHUNK 接收時每次都 seek，2MB 檔案需 10 秒」}

**現有約束**：
- ESP32 單核 160MHz
- 可用 RAM ~50KB
- 必須保持協議兼容性

**優化目標**：
{例如「減少到 3 秒以內」}

請提供：
- 優化方案（零拷貝/預分配/演算法改進）
- 修改後的程式碼
- 預期性能提升
```

---

## 📌 快速查找索引

| 我想...                    | 查看章節                  |
|----------------------------|---------------------------|
| 了解封包格式               | [§3 二進位封包協議](#3-二進位封包協議)         |
| 新增指令                   | [§6 Schema 驅動](#6-schema-驅動-payload-系統) + [§8 指令集](#8-指令集現況) |
| 雙核數據交換               | [§5 雙核心分工](#5-雙核心分工與同步機制)       |
| 回報狀態資訊               | [§4 SysBus](#4-三級數據總線-sysbus) (Providers) |
| 優化記憶體                 | [§10.4 記憶體管理](#104-記憶體管理最佳實踐)    |
| 理解專案演進               | [§2 系統架構演進](#2-系統架構演進)             |

---

**文件結束** — 若有更新請同步修改本文件頂部的「最後更新」時間戳

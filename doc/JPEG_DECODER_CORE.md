# JPEG Decode Core 架構與使用指南

這是一套全新的「JPEG 解碼核心模組」，專為 MicroPython (ESP32) 設計，旨在提供**低延遲、多圖層（label）調度、合作式分段解碼（step_blocks）**的零拷貝解碼管線。

此模組將「任務調度」與「解碼核心」徹底分離：解碼核心只管盡快完成當前任務、並提供同路徑跳過機制；何時給任務、給哪個 label 任務、幀率控制等，全由上游 Scheduler 負責。

## 核心設計理念

1. **For Label 輪詢**：系統維護一組 `source[]` 與 `output[]` lists，每個 list item 對應一個圖層 `label`（例如：background、mod、text）。解碼核心會不斷輪詢所有 label，尋找有新資料的 source_hub。
2. **單一 Job Lock（不混淆）**：一旦選定某個 label 的圖片開始解碼，解碼器就會被鎖定在該 Job，直到整張圖（所有 blocks）解完，才會挑選下一個 label 的任務。這確保了不同圖層的解碼進度不會互相混淆。
3. **Block Step（合作式多工）**：為了避免大圖解碼長時間霸佔 CPU 導致其它任務（網路、UI 等）餓死，解碼核心支援 `step_blocks`。每次 `loop()` 最多只解碼 N 個 block，隨後立刻 `return` 讓出 CPU，下一次 `loop()` 回來再繼續解這張圖。
4. **Skip by Hash**：支援 `path_hash` 驗證。如果上游 Scheduler 發現某個 label 需要顯示的圖片路徑與上一幀相同，解碼核心比對 `path_hash` 一致後會直接跳過，省下大量 CPU 時間。

---

## 模組與檔案結構

- **[jpeg_decoder_service.py](../slave/lib/jpeg_decoder_service.py)**
  提供 Service 註冊（`bus.register_service("jpeg_decoder")`）與從 `dp_config.json` 自動生成 source/output list 的輔助函式。
- **[jpeg_decode_core.py](../slave/tasks/jpeg_decode_core.py)**
  核心 Task 本體（`JpegDecodeCoreTask`），繼承自 `Task`，由 TaskManager 驅動。
- **[dp_config.json](../temp/dp_config.json)**
  使用者只需要維護這份設定檔，裡面的 `display_Layout` 會被用來自動生成所有 label 與其對應的 Hub。

---

## 系統架構圖

```text
+-------------------+      +-------------------+      +-------------------+
| Scheduler Task    |      | JpegDecodeCoreTask|      | Display/Render    |
| (任務調度/幀率控制) |      | (合作式解碼核心)   |      | (LCD 或影像合成)  |
+-------------------+      +-------------------+      +-------------------+
        |                            |                          |
        |  1. pack_in_header()       |                          |
        v  2. write jpeg bytes       v                          |
+-------------------+        +-------+-------+        +-------------------+
| source[label].hub | -----> | decode step N | -----> | output[label].    |
| (AtomicStreamHub) |        | (job locked)  |        | block_hub         |
+-------------------+        +---------------+        +-------------------+
                                                                |
                                                                v
                                                       3. read block payload
                                                       4. lcd.set_window()
                                                       5. lcd.write_data()
```

---

## Service 資料結構

從 `bus.get_service("jpeg_decoder")` 可以拿到如下結構：

```python
{
    "api": 1,
    "enable": True,
    "cfg": {
        "mode": "blocks",           # 預設 blocks
        "pixel_format": "RGB565_LE",
        "rotation": 0,
        "block": True,              # mp_jpeg block mode
        "step_blocks": 1,           # 每次 loop 解幾個 block
        "max_jpeg_bytes": 49152     # 從 fs.manifest 自動推導的最大檔 size
    },
    "cfg_epoch": 0,
    
    # 每個 label 的輸入
    "source": [
        {
            "label": "background",
            "hub": <AtomicStreamHub>,
            "enabled": True,
            "route_to": "background"
        },
        # ...
    ],
    
    # 每個 label 的輸出
    "output": [
        {
            "label": "background",
            "mode": "blocks",
            "block_hub": <AtomicStreamHub>,
            "meta": {"w":0, "h":0, "seq":0, "x0":0, "y0":0, "fmt":""},
            "enabled": True
        },
        # ...
    ],
    
    # 每個 label 的狀態（用於 skip 或 metrics）
    "state": [
        {
            "label": "background",
            "last_path_hash": 12345678,
            "decoded_frames": 0,
            "last_err": "",
            # ...
        }
    ]
}
```

---

## 如何使用 (開發指南)

### 1. 初始化與啟用

你只需要在準備進入 JPEG 模式時，載入 `dp_config.json` 並呼叫 `configure_from_dp_config`。`max_jpeg_bytes` 會自動根據 `fs.manifest` 掃描結果推算，不需要手填。

```python
from lib.sys_bus import bus
from lib.fs_manager import fs
from lib.jpeg_decoder_service import ensure_jpeg_decoder_service, load_dp_config, configure_from_dp_config

# 1. 確保 service 存在 (main.py 中已預設呼叫)
ensure_jpeg_decoder_service(bus)

# 2. 載入 dp_config
dp = load_dp_config("/sd/my_anim/dp_config.json")

# 3. 根據 dp_config 生成 labels 與 Hubs
configure_from_dp_config(
    bus, 
    dp_config=dp, 
    dp_config_path="/sd/my_anim/dp_config.json", 
    manifest=fs.manifest
)

# 4. 啟用 Task (指派給 Core 1 或 Core 0)
tm = bus.get_service("task_manager")
tm.set_affinity("jpeg_decode", (0, 1))  # 啟動在 Core 1
```

### 2. Scheduler 寫入任務 (Producer)

Scheduler 負責控制播放節奏。當要播放某一幀時，將檔案讀入 `source[label].hub`。
注意：必須使用 `pack_in_header` 寫入 16 bytes 的表頭。

```python
from lib.jpeg_decoder_service import pack_in_header

svc = bus.get_service("jpeg_decoder")
src = svc["source"][0] # 假設 label index 0 是 background
wv = src["hub"].get_write_view()

if wv is not None:
    path = "/sd/my_anim/bg/001.jpeg"
    path_hash = hash(path) & 0xFFFFFFFF
    
    # 讀取檔案
    with open(path, "rb") as f:
        n = f.readinto(wv[16:])
        
    # 寫入表頭 (payload_len, seq, x0, y0, flags, fmt_code, path_hash)
    # flags=0 (允許跳過), flags=1 (強制解碼不跳過)
    pack_in_header(wv, n, seq=1, x0=0, y0=0, flags=0, fmt_code=1, path_hash=path_hash)
    
    # 提交給解碼核心
    src["hub"].commit()
```

### 3. Display 消費結果 (Consumer)

解碼核心會將解碼後的 Block (8 或 16 行高) 寫入 `output[label].block_hub`。Display Task 只需要輪詢這些 hub 並推送到 LCD。

```python
from lib.jpeg_decoder_service import unpack_block_header

svc = bus.get_service("jpeg_decoder")
out = svc["output"][0] # background 的輸出
rv = out["block_hub"].get_read_view()

if rv is not None:
    # 解析 Block 表頭
    payload_len, seq, x, y, w, h, flags, fmt = unpack_block_header(rv)
    
    # 取出像素資料
    pixels = rv[16: 16 + payload_len]
    
    # 推送給 LCD
    lcd.set_window(x, y, x + w - 1, y + h - 1)
    lcd.write_data(pixels)
    
    # 如果 flags & 2 (LAST bit)，代表這張圖的最後一個 block 畫完了
    if flags & 2:
        print("Frame complete!")
        
    # rv 會在下一次呼叫 get_read_view() 時由 AtomicStreamHub 自動釋放
```

## Hub Header 協定定義

為了保持 Zero-copy 與避免 Python Object 轉換，所有控制訊號皆打包在 Buffer 的前 16 Bytes 內。

### Source Hub (IN_STRUCT)
長度: 16 Bytes
Format: `<HHhhHHI`
- `[0:2]` (u16): payload_len (JPEG 檔案大小)
- `[2:4]` (u16): seq (任務序號)
- `[4:6]` (i16): x0 (繪製起始 X 座標)
- `[6:8]` (i16): y0 (繪製起始 Y 座標)
- `[8:10]` (u16): flags (Bit0: FORCE 不跳過)
- `[10:12]` (u16): fmt_code
- `[12:16]` (u32): path_hash (路徑雜湊，相同 hash 會觸發跳過機制)

### Output Block Hub (OUT_STRUCT)
長度: 16 Bytes
Format: `<HHhhHHHH`
- `[0:2]` (u16): payload_len (此 block 的像素大小 bytes)
- `[2:4]` (u16): seq
- `[4:6]` (i16): x (此 block 的 X 座標)
- `[6:8]` (i16): y (此 block 的 Y 座標)
- `[8:10]` (u16): w (block 寬度)
- `[10:12]` (u16): h (block 高度)
- `[12:14]` (u16): flags (Bit0: FIRST block, Bit1: LAST block)
- `[14:16]` (u16): fmt_code

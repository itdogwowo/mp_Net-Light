# 協議層吞吐優化方案

## 1. 背景

目前有效吞吐（含完整協議層：CRC32 + Schema decode + Dispatch + Marshalling）約 **400~500 KB/s**。

經測試：
- TCP 裸傳輸能力：**2~3 MB/s**
- CRC32 解碼速度（純 MicroPython）：**4~5 MB/s**
- 協議層損失約 **75~83%**，瓶頸不在網路層，也不在校驗，而在：

```
Schema decode (JSON 載入 + Python dict 解碼)
Dispatch lookup (dict hash lookup)
Byte marshalling (struct.unpack / 逐 byte 組合)
dict 頻繁 alloc/free 觸發 GC
```

本文件記錄一系列無需脫離 MicroPython 即可執行的優化手段，目標是將有效吞吐提升至 **2~3 MB/s**（接近裸 TCP 上限）。

---

## 2. 瓶頸分析與優化對策一覽

| 瓶頸 | 目前實作 | 優化手法 | 預期提升 |
|------|---------|---------|:-------:|
| Dispatch lookup | dict hash lookup `_handlers.get(cmd_id)` | 預分配陣列 O(1) 索引 | **3~5x** |
| Schema decode | runtime `ujson.loads()` + dict 重複建立 | 預編譯 layout + decode cache | **3~4x** |
| Byte marshalling | `struct.unpack` / Python 逐 byte | Viper `ptr8`/`ptr32` 直接操作 | **5~10x** |
| dict GC trashing | 每次 decode 新建 dict | 預分配 + `dict.clear()` 重用 | 消除 GC spikes |

---

## 3. 優化手法詳細說明

### 3.1 Dispatch：dict lookup → 陣列索引

#### 目前作法

```python
_handlers = {}

def register(cmd_id, handler):
    _handlers[cmd_id] = handler

def dispatch(cmd_id, payload):
    handler = _handlers.get(cmd_id)  # dict hash lookup
    return handler(payload)
```

dict 雖然是 O(1) amortized，但 hash 計算 + 碰撞處理在 MicroPython 上有不可忽略的 overhead。

#### 優化方案

```python
import micropython

MAX_CMD = 0x4000  # 16384 個 slot (覆蓋所有 cmd_id)
_HANDLERS = [None] * MAX_CMD

def register(cmd_id, handler):
    _HANDLERS[cmd_id] = handler

@micropython.viper
def dispatch(cmd_id: int, payload):
    h = _HANDLERS[cmd_id]
    if h:
        return h(payload)
```

#### 效果
- 陣列索引在 Viper 中編譯為 `base + index * sizeof(ptr)`，單一指令
- 無 hash 計算、無碰撞處理、無型別檢查
- 對高頻指令（如 `0x3003 STREAM_DIRECT`、`0x1812 RAM_BENCH_CHUNK`）改善最明顯
- 約 **3~5x**

---

### 3.2 Schema decode：預編譯 + decode cache

#### 目前作法

```python
def decode(schema_name, raw_bytes):
    schema = json.loads(open(f"schema/{schema_name}.json").read())
    # 動態遍歷 schema 欄位、逐 byte 解析
```

問題：
1. 每次 decode 都要 `ujson.loads()` — C 函數調用 overhead 很大
2. 每次回傳新的 dict — GC 壓力
3. JSON 是 runtime 直譯型格式，無法編譯期最佳化

#### 優化方案 A：預編譯 schema layout

在 PC 端（或開機時一次性）將 JSON schema 轉成 tuple-based layout：

```python
# 例如 stream.json 的 STREAM_STATE_SET payload:
# { file_name: string, block_id: uint16, play_mode: uint8 }

# 編譯成：
STREAM_STATE_SET_LAYOUT = (
    ('file_name', 's', 0, 32),    # name, type, offset, length
    ('block_id',  'H', 32, 2),
    ('play_mode', 'B', 34, 1),
)
```

decode 時直接照 layout 讀取，不碰 JSON：

```python
import struct

def decode_stream_state_set(data):
    return {
        'file_name': data[0:32].rstrip(b'\x00').decode(),
        'block_id': struct.unpack_from('<H', data, 32)[0],
        'play_mode': data[34],
    }
```

進一步可用 Viper 加速：

```python
@micropython.viper
def decode_stream_state_set_viper(data: ptr8) -> dict:
    d = _DECODE_CACHE['stream_state_set']
    d.clear()
    # file_name: 先把 bytes 摳出來 (Viper 不擅長字串，保留 Python 層)
    # block_id: uint16 little-endian
    d['block_id'] = int(data[32]) | (int(data[33]) << 8)
    d['play_mode'] = int(data[34])
    return d
```

#### 優化方案 B：decode cache 消除 GC

```python
# 預分配每個 schema 的 decode result dict
_DECODE_CACHE = {
    'stream_state_set': {},
    'stream_direct': {},
    'file_chunk': {},
    # ...
}

def decode(schema_name, data):
    d = _DECODE_CACHE[schema_name]
    d.clear()  # 不釋放 memory，只清 entries
    # ... 填入資料
    return d
```

#### 效果
- 省掉 `ujson.loads()`（最大的 C 函數調用）
- 省掉 dict 反覆 alloc/free（GC 不再被高頻 decode 觸發）
- 約 **3~4x**

---

### 3.3 Byte marshalling：Viper ptr 直接操作

#### 目前作法

```python
block_id = (data[0] << 8) | data[1]
frame_id = (data[2] << 24) | (data[3] << 16) | (data[4] << 8) | data[5]
```

或

```python
block_id, frame_id = struct.unpack_from('<HI', data, 0)
```

#### 優化方案

```python
@micropython.viper
def unpack_header(data: ptr8) -> (int, int):
    p32 = ptr32(data)        # 視為 uint32 陣列
    cmd_id = p32[0]          # 一次讀 4 bytes
    addr   = p32[1]
    length = p32[2]
    return int(cmd_id), int(addr), int(length)
```

對於 payload 中的連續欄位：

```python
@micropython.viper
def unpack_payload_2u16_1u32(data: ptr8) -> (int, int, int):
    p16 = ptr16(data)
    p32 = ptr32(data)
    val_a = int(p16[0])       # uint16 at offset 0
    val_b = int(p16[1])       # uint16 at offset 2
    val_c = int(p32[1])       # uint32 at offset 4 (小端)
    return val_a, val_b, val_c
```

#### 效果
- `ptr32[0]` = 一次讀 4 bytes = 1 條 ARM 指令
- 相比 Python 4 次 `data[i]` + 3 次 shift + 3 次 OR = ~11 條 bytecode
- 約 **5~10x**

---

### 3.4 組合預期圖表

```
原始 (MicroPython 純 Python)
  CRC decode:        4~5 MB/s    ✅ 夠快
  Schema decode:     ~1 MB/s     ❌ 瓶頸
  Dispatch lookup:   ~3 MB/s     ⚠️
  Marshalling:       ~2 MB/s     ⚠️
  ─────────────────────────────────
  有效吞吐:          ~500 KB/s   (受最慢環節限制)

優化後 (Viper + 預編譯 + 陣列 dispatch)
  CRC decode:        4~5 MB/s    ✅
  Schema decode:     ~4 MB/s     ✅ 預編譯 layout + cache
  Dispatch lookup:   ~8 MB/s     ✅ 陣列 O(1)
  Marshalling:       ~6 MB/s     ✅ Viper ptr 操作
  ─────────────────────────────────
  有效吞吐:          ~3~4 MB/s   (逼近裸 TCP 上限)
```

協議層損失從 **75% 降至 ~30%**（剩下主要是 TCP/IP 協議棧本身的 MicroPython 實現 overhead）。

---

## 4. 實作順序建議

### Phase 1（低風險，立即見效）
1. **Dispatch 陣列化** — `dispatch.py` 改動，完全不影響 handler 邏輯
2. **decode cache** — `schema_codec.py` 加上 `_DECODE_CACHE`，現有 decode 函數不變

預期效果：有效吞吐 **500 KB/s → 1~1.5 MB/s**

### Phase 2（中等改動，逐個 schema 遷移）
3. 從最高頻的 schema 開始預編譯：
   - `stream.json` 的 `STREAM_DIRECT (0x3003)` — 這是最頻繁的指令
   - `ram_bench.json` 的 `RAM_BENCH_CHUNK (0x1812)` — 測速用
   - `file.json` 的 `FILE_CHUNK (0x2002)` — 檔案傳輸
4. 新加 `schema_compiled.py` 或 `schema/compiled/` 目錄存放預編譯 layout

預期效果：有效吞吐 **1~1.5 MB/s → 2~2.5 MB/s**

### Phase 3（追求極致）
5. 關鍵路徑上的 marshalling 改用 Viper `ptr8`/`ptr16`/`ptr32`
6. 用 `@micropython.native` 或 `@micropython.viper` 裝飾 decode 函數
7. 加入 `perf_counter` 量測每個環節的耗時，找出剩餘瓶頸

預期效果：有效吞吐 **2~2.5 MB/s → 3~4 MB/s**

---

## 5. 補充：MicroPython 加速可用工具對照（ESP32 / Xtensa）

> 注意：ESP32 使用 **Xtensa** 架構，`asm_thumb` (ARM) 無法使用。

| 工具 | 適用場景 | 加速比 | 限制 |
|------|---------|:-----:|------|
| `@micropython.viper` | **⭐ 主力加速工具** — 整數運算、ptr 操作、迴圈 | **2~10x** | 不能操作 Python object、字串、list/dict |
| `@micropython.native` | 一般 Python 函數編譯成 native code | **1.5~3x** | 不能有任意跳轉 / closure |
| `@micropython.asm_xtensa` | 極致優化（Xtensa 組合語言） | **8~15x** | 需懂 Xtensa ISA；MicroPython 支援度不如 viper 成熟 |
| `frozen modules` | 將 .py 預編譯進 firmware，省去 import compile time | 省開機時間 | 需重新 build firmware 燒錄 |
| 預分配 buffer (`bytearray`) | 消除高頻 alloc/free 觸發的 GC | 不直接加速但消除卡頓 | 需手動管理 buffer 生命週期 |
| `dict.clear()` 重複使用 | 消除 decode 時反覆新建 dict 的 GC 壓力 | 同上 | 需確保 caller 不保留舊引用 |
| `struct.pack_into` / `unpack_from` | 使用 memoryview offset 避免建立臨時 bytes | 少量加速 | API 略麻煩 |

### 實務建議（ESP32 上）

**Viper 是你最該投資的工具**，它直接編譯成 Xtensa native code，而且語法跟 Python 87% 像。`asm_xtensa` 理論上更快，但文件少、坑多，非必要不碰。

Phase 1~3 提到的優化全部只用 `viper` + `native` + 預分配技巧就能達成，不需要碰組合語言。

---

## 6. 驗證方式

1. 使用 `RAM_BENCH` 協議（`mode=0 discard`）測量純協議層吞吐
2. 對比優化前後的 `mb_s_x1000` 回報值
3. 比對 `performance_report.md` 的 400~500 KB/s 基線

---
## 7. DMA 直接操作暫存器（未來項目）

本專案的協議層優化不涉及 DMA。但經過討論，記錄以下供其他項目參考：

### MicroPython 上操作 DMA 的現實

`machine.mem32[addr] = val` 可以直接讀寫硬體暫存器（包括 GDMA），但有以下限制：

| 問題 | 原因 |
|------|------|
| DMA buffer memory type | MicroPython heap 可能在 PSRAM 上，DMA 只能使用內部 DRAM |
| Cache coherency | CPU 寫了 buffer 但 DMA 讀到 stale data，MicroPython 無法執行 `dpandb` |
| Descriptor 手動填 | DMA descriptor 是 64-byte struct，需用 `mem32` 逐字節填入 linked list |
| 中斷 latency | MicroPython `irq()` callback ~50µs，吃掉 DMA 的低延遲優勢 |
| Buffer alignment | DMA 要求 16/32-byte aligned，`bytearray` 不保證 |

### 建議做法

```python
# 不建議：mem32 硬幹 DMA 暫存器
mem32[GDMA_CH0_DESC_ADDR] = desc_addr  # 不穩定，難 debug

# 建議：寫 C module 包裝 ESP-IDF GDMA API
# dma_streamer.c → compile into firmware → Python import
import dma_streamer
dma_streamer.apa102_write(spi_buffer, len)  # 全速 DMA
```

C module 方式可保留 `apa102.py` 的 `buf / spi_buffer` 結構，僅替換最底層的 `show_raw()` 實現。

### 參考資源

- [`doc/RAM_BENCH.md`](./RAM_BENCH.md) — RAM 測速協議細節
- [`doc/performance_report.md`](./performance_report.md) — 當前性能基線
- [`slave/lib/dispatch.py`](../slave/lib/dispatch.py) — Dispatch 實作
- [`slave/lib/schema_codec.py`](../slave/lib/schema_codec.py) — Schema codec 實作

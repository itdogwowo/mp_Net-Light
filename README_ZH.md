<div align="center">

# mp_Net-Light

**MicroPython 網路化 LED 控制系統**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-ESP32|S3|P4-green.svg)]()
[![MicroPython](https://img.shields.io/badge/MicroPython-≥1.26-orange.svg)]()

*不只是又一臺 LED 控制器。雙核心、協議驅動、異質燈光平臺。*

---

</div>

## 概述

**mp_Net-Light** 是一套基於 **ESP32 / S3 / P4 + MicroPython** 的高效能網路化 LED 控制系統。它將微控制器轉變為完整的**網路節點**，可同時驅動 **WS2812、APA102 與 PCA9685**，透過 TCP/WebSocket 即時控制，與 xLights 序列同步播放，並配備工業級檔案傳輸與原子寫入機制。

不同於 WLED（通用家居燈光）或 FPP（大規模序列播放器），mp_Net-Light 站在獨特的交點：

- **純 Python 開發** — 秒級迭代，無需 C 工具鏈
- **真正的雙核心架構** — Core 0 專責網路，Core 1 專責渲染，互不競爭
- **異質 LED 混合輸出** — 一臺 ESP32 同時驅動 WS2812 + APA102 + PCA9685，共用統一緩衝區
- **協議驅動設計** — Schema 定義指令，擴展無需重新編譯
- **xLights 序列支援** — PXLD v3 格式橋接專業燈光設計到 MicroPython 播放

---

## 支援硬體

| SoC | 核心 | 有線網路 | WiFi | 狀態 |
|-----|------|---------|------|------|
| **ESP32** (LX6) | 2× Xtensa | RMII + SPI (W5500) | 2.4 GHz | ✅ 主要目標 |
| **ESP32-S3** (LX7) | 2× Xtensa | SPI (W5500) | 2.4 GHz | ✅ 網路驗證完成 |
| **ESP32-P4** (RISC-V) | 2× RISC-V | RMII | ❌ 無 WiFi | ✅ 有線網路驗證 (~1ms ping) |

三款皆支援 MicroPython ≥1.26，完整 Viper 原生程式碼編譯。

---

## 架構

```
                    ┌──────────────────────────────────────────┐
                    │            ESP32 雙核心                   │
                    │                                          │
Core 0 (網路核心)   │            Core 1 (渲染核心)              │
                    │                                          │
┌──────────────────┐│  ┌─────────────────────────────────────┐ │
│  Network Task    ││  │  Render Task                        │ │
│  · TCP/WS/UDP    ││  │  · 從 AtomicStreamHub 消費資料      │ │
│  · Bus Decode    │◀──▶  · LEDController.show_all()          │ │
│  · Supply Chain  ││  │  · 維持幀率定時                      │ │
│  · Web UI        ││  └─────────────────────────────────────┘ │
└────────┬─────────┘│                                          │
         │          │                                          │
         ▼          │                                          │
┌──────────────────┐│                                          │
│  AtomicStreamHub ││  零拷貝、無鎖環形緩衝區                   │
│  (三槽狀態機)     ││  IDLE → READY → READING                 │
└──────────────────┘│                                          │
                    └──────────────────────────────────────────┘
         │                          │
         │     SysBus (服務註冊、    │
         │     動態回報、共享狀態)    │
         │                          │
┌────────▼──────────────────────────▼──────────────────────────┐
│                    電腦端控制                                   │
│  · Django 伺服器 (WebSocket + REST + Web UI)                  │
│  · NetBusMaster 指令端 (直接 TCP 控制，無需伺服器)            │
│  · PXLD v3 解碼器，支援 xLights 序列播放                      │
│  · UDP 心跳自動發現設備                                       │
└──────────────────────────────────────────────────────────────┘
```

**Core 0** 處理所有 I/O：TCP/WebSocket 連線、二進位協定解析、Schema 解碼、檔案系統操作。**Core 1** 專職 LED 渲染：從無鎖 `AtomicStreamHub` 消費幀資料、執行 Viper 加速的像素格式轉換、驅動實體 LED 硬體。

核心間通訊透過 `AtomicStreamHub` — 一種多槽位環形緩衝區，使用原子狀態轉換（`IDLE → READY → READING`），不需要鎖、不產生 GC 壓力。

---

## 功能特色

### 核心系統

| 功能 | 說明 |
|------|------|
| **雙核心架構** | Core 0 網路 I/O，Core 1 LED 渲染 — 負載下不掉幀 |
| **Schema 驅動協議** | JSON Schema 定義指令，新增指令無需重新編譯韌體 |
| **AtomicStreamHub** | 無鎖、零拷貝、三槽環形緩衝區，跨核心資料傳輸 |
| **SysBus** | 服務註冊、動態回報、共享狀態 — 設備的神經系統 |
| **任務編排器** | 註冊任務並指定核心親和性，可在執行時遷移任務 |
| **指令端工具** | `NetBusMaster.py` 直接 TCP/WS 控制設備，不需依賴伺服器 |
| **效能基準測試** | 內建 RAM 頻寬測試（discard/copy/hub_copy 三種模式） |

### LED 驅動

| 驅動 | 類型 | 介面 | 速度 | 特色 |
|------|------|------|------|------|
| **WS2812 / NeoPixel** | 單線 | GPIO | MicroPython RMT 級時序 | 多燈帶、可設色序 |
| **APA102 / DotStar** | SPI | 硬體 SPI (8 MHz) | Viper 加速幀轉換 | 雙緩衝、亮度頭部 |
| **PCA9685** | I2C PWM | I2C (400 kHz) | 16 通道、12-bit 解析度 | Viper 加速暫存器填裝 |

**獨有能力**：三種驅動可從同一個 RGBW 統一幀緩衝區**同時輸出**。單次 `LEDStreamer.show_all()` 呼叫即可完成 WS2812 燈帶、APA102 燈帶與 PCA9685 PWM 通道的轉換與輸出。

### 網路

| 介面 | 類型 | 說明 |
|------|------|------|
| **WiFi STA** | 無線 | 自動連線，設定失敗時回退 AP 模式 |
| **WiFi AP** | 無線 | 安全熱點，無需螢幕即可設定 |
| **RMII 乙太網路** | 有線 | LAN8720 / IP101 PHY 支援（ESP32、ESP32-P4） |
| **SPI 乙太網路** | 有線 | WIZNET5K (W5500) 支援（ESP32、ESP32-S3） |

| 協定 | 傳輸層 | 用途 |
|------|--------|------|
| **NetBus 二進位** | TCP / WebSocket | 主要控制通道，CRC32 驗證 |
| **UDP 發現** | UDP 廣播 | 設備心跳與自動發現 |
| **HTTP** | TCP | 內建 Web UI（埠 80） |
| **mDNS** | UDP | 區域網路名稱解析 |

### 控制方式

不需要 Django 伺服器也能控制設備，兩種選擇：

- **Django 伺服器** (`server/`)：完整的 WebSocket 控制、REST API、Web UI、PXLD 播放管理、設備發現面板
- **NetBusMaster 指令端** (`tools/NetBusMaster.py`)：直接 TCP/WebSocket 控制 — 發送指令、管理檔案、執行基準測試、控制播放。**零伺服器設定。**

### 序列播放

```
xLights (燈光設計軟體)
    ↓ 渲染 RGB 資料
[轉換器] → PXLD v3 檔案 (.pxld)
    ↓ PXLDv3Splitter
每個 slave 獨立的 .bin 檔 (原始 RGBW 幀)
    ↓ TCP 檔案傳輸 (原子寫入 + SHA256 驗證)
ESP32 本地快閃記憶體 / SD 卡
    ↓ PLAY 指令 + 未來時間同步
從本地儲存進行雙核心播放
    ↓ LED 輸出 (WS2812 / APA102 / PCA9685)
```

- **xLights 整合**：將 xLights 輸出的序列轉為 PXLD v3，再按 slave 分割
- **本地播放**：完整序列儲存在 ESP32 快閃記憶體/SD 卡 — 播放過程完全不依賴網路
- **幀精確同步**：未來時間 PLAY 指令實現次毫秒級多設備同步
- **Seek、暫停、循環**：透過協議指令完整控制

### 檔案傳輸

- **區塊上傳**支援斷點續傳
- **原子寫入**：檔案僅在 SHA256 驗證通過後才完成寫入
- **檔案清單快取**：加速目錄查詢速度
- **完整檔案系統掃描**：按需掃描並生成清單

### 系統管理

- **OTA 檔案更新**：透過網路推送新 Python 模組 — 無需重新燒錄韌體
- **WiFi 掃描**：依需求列出附近可用基地台
- **配置持久化**：JSON + BTree 資料庫；密碼自動隔離至安全儲存區
- **內建 Web UI**：設備本身提供控制面板，任何瀏覽器皆可存取
- **WebSocket 監控**：即時 FPS、幀計數、設備指標

---

## 效能

| 指標 | 數值 | 條件 |
|------|------|------|
| **TCP 裸傳輸** | 2~3 MB/s | ESP32 WiFi，無協議處理 |
| **有效吞吐（完整協議栈）** | 400~500 KB/s | CRC32 + Schema 解碼 + Dispatch + Hub 傳輸 |
| **CRC32 解碼速度** | 4~5 MB/s | MicroPython 搭配 Viper 最佳化 |
| **LED 渲染** | 40+ FPS @ 1000+ 顆 LED | 雙核心 + `@micropython.viper` 轉換 |
| **有線網路延遲** | ~1ms | RMII PHY / ESP32-P4，無 WiFi 抖動 |
| **S3 網路測試** | ✅ 驗證完成 | ESP32-S3 搭配 W5500 乙太網路已測試 |

**擴展性**：40 FPS 下，500 KB/s 可支援約 3200 顆 RGBW LED。更大規模的安裝可將序列預載至本地快閃記憶體，播放效能不受網路吞吐限制。

**未來優化空間（相同硬體、相同 MicroPython）**：

| 優化項目 | 預期提升 | 方法 |
|:--------|:-------:|------|
| Dispatch 陣列查表 | 3~5x | 預分配陣列取代 dict |
| Schema 解碼快取 | 3~4x | 預編譯 layout + `dict.clear()` 重用 |
| Viper byte marshalling | 5~10x | `ptr8`/`ptr32` 直接記憶體存取 |

目標：**有效吞吐 2~3 MB/s**（詳見 [`doc/PROTOCOL_OPTIMIZATION_PLAN.md`](doc/PROTOCOL_OPTIMIZATION_PLAN.md)）

---

## 專案結構

```
mp_Net-Light/
├── slave/                          # ESP32 MicroPython 韌體
│   ├── boot.py                     # 硬體初始化 (SPI, I2C, LED, SD)
│   ├── main.py                     # 入口：TaskManager + 雙核心啟動
│   ├── app.py                      # App：SchemaStore + Dispatcher 組合
│   ├── config.json                 # 設備設定 (LED、網路、匯流排)
│   ├── lib/                        # 核心函式庫
│   │   ├── sys_bus.py              # 服務註冊 + 共享狀態
│   │   ├── proto.py                # 二進位封包 (SOF/CRC/編解碼)
│   │   ├── dispatch.py             # 指令分發器
│   │   ├── schema_codec.py         # Schema 驅動 Payload 編解碼
│   │   ├── net_bus.py              # 網路傳輸抽象層
│   │   ├── network_manager.py      # WiFi/乙太網路介面管理器
│   │   ├── task.py                 # 任務基礎類別
│   │   ├── task_manager.py         # 雙核心任務編排器
│   │   ├── buffer_hub.py           # AtomicStreamHub (無鎖環形緩衝)
│   │   ├── fs_manager.py           # 檔案系統 + SHA256 驗證
│   │   ├── LEDController.py        # 統一 LED 驅動控制器
│   │   ├── apa102.py               # APA102 SPI 驅動 (Viper 加速)
│   │   ├── pca9685.py              # PCA9685 I2C PWM 驅動
│   │   └── ConfigManager.py        # JSON + BTree 設定持久化
│   ├── action/                     # 指令處理器
│   │   ├── registry.py             # 指令註冊中心
│   │   ├── stream_actions.py       # LED 串流播放/暫停/跳轉
│   │   ├── file_actions.py         # 檔案傳輸 BEGIN/CHUNK/END
│   │   ├── sys_actions.py          # 系統發現/連線
│   │   ├── status_actions.py       # 狀態查詢/回報
│   │   ├── heartbeat_actions.py    # UDP 心跳廣播
│   │   └── ram_bench_actions.py    # RAM 頻寬基準測試
│   ├── tasks/                      # 背景任務 (指定核心親和性)
│   │   ├── network.py              # Core 0：網路 I/O
│   │   ├── bus_decode.py           # Core 0：協定解碼
│   │   ├── render.py               # Core 1：LED 渲染
│   │   └── web_ui.py               # Core 0：內建網頁伺服器
│   └── schema/                     # 協定 Schema 定義
│       ├── sys.json                # 系統指令
│       ├── status.json             # 狀態指令
│       ├── heartbeat.json          # 心跳指令
│       ├── file.json               # 檔案傳輸指令
│       ├── stream.json             # 串流播放指令
│       └── ram_bench.json          # RAM 基準測試指令
├── server/                         # 電腦端 Django 伺服器 (可選)
│   ├── core/                       # 發現 + 協定服務
│   └── light_control/              # WebSocket 播放 + REST API
├── tools/                          # 電腦端工具 (指令操作，不需伺服器)
│   ├── NetBusMaster.py             # 完整設備管理主控台
│   ├── PXLDv3Splitter.py           # xLights 序列 → 各 slave .bin
│   └── pc_test_tool.py             # 電腦端測試與基準
├── doc/                            # 設計文件
│   ├── AI_CONTEXT.md               # 完整系統參考
│   ├── DualCoreTaskOrchestrator.md  # 雙核心任務設計
│   ├── PROTOCOL_OPTIMIZATION_PLAN.md # 協定吞吐優化
│   ├── RAM_BENCH.md                 # RAM 基準測試協定
│   └── performance_report.md        # 當前效能基準
└── function test/                   # 單元與整合基準測試
```

---

## 文件

| 文件 | 說明 |
|------|------|
| [`doc/AI_CONTEXT.md`](doc/AI_CONTEXT.md) | 完整系統參考：架構、協定、Schema、雙核心設計 |
| [`doc/DualCoreTaskOrchestrator.md`](doc/DualCoreTaskOrchestrator.md) | 任務生命週期、親和性、AtomicStreamHub 設計 |
| [`doc/PROTOCOL_OPTIMIZATION_PLAN.md`](doc/PROTOCOL_OPTIMIZATION_PLAN.md) | 協定吞吐優化：Viper、Dispatch 陣列、Schema 快取 |
| [`doc/performance_report.md`](doc/performance_report.md) | 網路效能基準與調校結果 |
| [`doc/RAM_BENCH.md`](doc/RAM_BENCH.md) | RAM 頻寬基準測試協定細節 |

---

## 對比

| 面向 | mp_Net-Light | WLED | FPP (Falcon Player) |
|------|:------------:|:----:|:-------------------:|
| **開發語言** | MicroPython | C++ (Arduino) | C++ / Python |
| **目標硬體** | ESP32 / S3 / P4 | ESP8266 / ESP32 | Raspberry Pi / BeagleBone |
| **雙核心架構** | ✅ 明確任務分離 | ❌ | ❌ (Linux 行程) |
| **異質 LED 混合** | ✅ WS2812+APA102+PCA9685 | ❌ 單一類型 | ✅ 透過硬體通道 |
| **內建特效** | ❌ (播放為核心) | ✅ 117+ 種特效 | ✅ 透過 xLights 序列 |
| **xLights 整合** | ✅ PXLD v3 轉換器 | ⚠️ 部分 (UDP realtime) | ✅ 原生支援 |
| **有線網路** | ✅ RMII + SPI (W5500) | ❌ 僅 WiFi | ✅ (主要介面) |
| **通訊協定** | Schema 驅動二進位 (TCP/WS) | JSON API + E1.31/Art-Net | E1.31 / DDP / DMX |
| **檔案傳輸** | 原子寫入 + SHA256 驗證 | 基本設定備份 | Linux 檔案系統 |
| **OTA 更新** | 推送 Python 檔 (不重燒) | 完整韌體重燒 | 套件管理員 |
| **控制方式** | Django 伺服器 **或** 指令端 CLI | Web UI + 行動 App | FPP Web UI |
| **開發週期** | 編輯 → 上傳 → 執行 (~10 秒) | 編輯 → 編譯 → 燒錄 (~2 分鐘) | 編輯 → 建置 → 部署 |
| **目標使用者** | 開發者、藝術家、客製安裝 | 一般居家使用者 | 專業燈光秀 |

### 這個專案不是什麼

- **不是 WLED 的替代品** — WLED 擅長開箱即用的居家燈光，擁有 117+ 特效和精美的 UI。當你需要「30 分鐘搞定智慧燈光」時，請用 WLED。
- **不是 FPP 的競爭者** — FPP 透過專用硬體控制器驅動數十萬顆 LED，是專業聖誕燈光和舞台燈光的標準。
- **一把不同的刀，切不同的任務** — mp_Net-Light 是為**開發者和創作者**設計的，適合需要自訂協定邏輯、異質 LED 硬體、在 Python 層級控制雙核心排程、並且能夠修改每一層程式碼的人。

---

## 快速開始

### 硬體需求

- ESP32 / ESP32-S3 / ESP32-P4 開發板（建議配備 PSRAM）
- USB 傳輸線（用於初次燒錄 MicroPython）
- LED 燈帶：WS2812、APA102 或基於 PCA9685 的 PWM LED
- （選配）RMII 乙太網路 PHY（LAN8720/IP101）或 SPI 乙太網路（W5500）
- （選配）MicroSD 卡模組（用於儲存大型序列）

### 軟體設定

1. **燒錄 MicroPython ≥1.26** 至開發板
2. **上傳 `slave/` 目錄** 至設備檔案系統
3. **設定** `slave/config.json`，根據你的 LED 和網路環境調整
4. 選擇控制方式：
   - **指令端**：`python tools/NetBusMaster.py`（不需伺服器，直接控制）
   - **伺服器**：`cd server && pip install -r requirements.txt && python manage.py runserver`
5. **開機** — 設備會自動透過 WebSocket 連線

---

## 授權

[MIT](LICENSE)

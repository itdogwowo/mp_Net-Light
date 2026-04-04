# TFT 顯示器設定（Config 驅動）

本專案的 TFT 顯示器驅動位於 [TFT.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/TFT.py)。系統會在開機階段依 `config.json` 的 `TFT` 設定自動初始化，並註冊為 `lcd` service，供 JPEG 顯示/合成任務使用。（向後相容舊的 `Display` 設定鍵）

## 快速開始

1. 確認 `SPI.enable=1` 且 `SPI.list` 已建立對應的 SPI（boot 會註冊 `spi_list`）。
2. 在 `config.json` 內新增/修改 `TFT` 區塊並設 `enable=1`。
3. 重開機後，若初始化成功，可透過 `bus.get_service("lcd")` 取得物件，並呼叫：
   - `lcd.set_window(x0, y0, x1, y1)`
   - `lcd.write_data(pixel_bytes)`

## config.json 範例

以下為建議的最小 `TFT` 結構（只需要設定 GPIO 與 dp_config 路徑；其他顯示參數若未提供會使用預設值）：

```json
{
  "TFT": {
    "enable": 1,
    "dp_config_path": "/sd/dp_config.json",
    "GPIO": {
      "spi": 0,
      "dc": 2,
      "cs": 3,
      "rst": 4
    }
  }
}
```

## 欄位說明

- `enable`: 1 啟用，0 關閉。
- `dp_config_path`: dp_config.json 的路徑；若有填入且 `auto_start=1`（預設 1），開機會自動載入並初始化 `jpeg_decoder`（labels/hubs）。
- `auto_start`（可選）: 1 則自動啟動 `jpeg_decode` 與 `display` 兩個 tasks；0 則只初始化 TFT，不啟動 tasks。
- `task_core`（可選）: 指定自動啟動的 tasks 跑在哪個 core（0 或 1），預設 1。
- `GPIO.spi`: 使用 `spi_list` 的索引（與 APA102 設定方式相同）。
- `GPIO.dc/cs/rst`: 對應的 GPIO 腳位編號。
- `driver`（可選）: 驅動類別名稱（對應 [TFT.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/TFT.py) 內的 class 名稱），預設 `ST7789`。
  - 常用：`ST7735`、`ST7789`、`ST7789T3`、`GC9A01`、`ILI9341`
- `width` / `height`（可選）: 顯示器解析度（像素）。未提供時會嘗試從 `dp_config.tft.width/height` 取得，仍沒有則用 `240x240`。
- `rotation`（可選）: `0/90/180/270`，預設 0。
- `color_order`（可選）: `RGB` 或 `BGR`，預設 `RGB`。
- `invert`（可選）: 1 開啟反相，0 關閉，預設 0。
- `GPIO.bl` / `GPIO.bl_invert`（可選）: 若你要由系統直接控制背光才需要設定；若背光由 LED Controller 管理，可省略。
- `init_fill`（可選）: 初始化後先填滿螢幕。
  - `0`/`false`: 不做
  - `1`/`true`: 填黑色
  - `[r,g,b]`: 例如 `[0,0,0]` 黑、`[255,255,255]` 白
  - `RGB565 int`: 例如 `0xFFFF` 白、`0xF800` 紅

## 註冊的 services

- `lcd`: TFT driver instance（必要）。
- `tft`: 同 `lcd`，提供另一個別名。
- `lcd_bl`: 若 `GPIO.bl >= 0` 則註冊背光 Pin 物件。

## dp_config 內的顯示器設定（可選）

若你希望「除了 GPIO 以外」都由 dp_config 控制，可在 dp_config.json 內加入：

```json
{
  "tft": {
    "driver": "ST7789",
    "width": 240,
    "height": 240,
    "rotation": 0,
    "color_order": "RGB",
    "invert": 0,
    "init_fill": 1
  }
}
```

## 相關程式位置

- 初始化邏輯： [boot.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/boot.py) 的 `init_display()`
- 驅動實作： [TFT.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/TFT.py)

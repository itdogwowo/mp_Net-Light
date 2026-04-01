# TFT 顯示器設定（Config 驅動）

本專案的 TFT 顯示器驅動位於 [TFT.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/TFT.py)。系統會在開機階段依 `config.json` 的 `Display` 設定自動初始化，並註冊為 `lcd` service，供 JPEG 顯示/合成任務使用。

## 快速開始

1. 確認 `SPI.enable=1` 且 `SPI.list` 已建立對應的 SPI（boot 會註冊 `spi_list`）。
2. 在 `config.json` 內新增/修改 `Display` 區塊並設 `enable=1`。
3. 重開機後，若初始化成功，可透過 `bus.get_service("lcd")` 取得物件，並呼叫：
   - `lcd.set_window(x0, y0, x1, y1)`
   - `lcd.write_data(pixel_bytes)`

## config.json 範例

以下為預設已加入的 `Display` 結構（你只需要調整 GPIO 與 driver/解析度）：

```json
{
  "Display": {
    "enable": 1,
    "driver": "ST7789",
    "width": 240,
    "height": 240,
    "rotation": 0,
    "color_order": "RGB",
    "invert": 0,
    "GPIO": {
      "spi": 0,
      "dc": 2,
      "cs": 3,
      "rst": 4,
      "bl": -1,
      "bl_invert": 0
    },
    "init_fill": 0
  }
}
```

## 欄位說明

- `enable`: 1 啟用，0 關閉。
- `driver`: 驅動類別名稱（對應 [TFT.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/TFT.py) 內的 class 名稱）。
  - 常用：`ST7735`、`ST7789`、`ST7789T3`、`GC9A01`、`ILI9341`
- `width` / `height`: 顯示器解析度（像素）。
- `rotation`: `0/90/180/270`。
- `color_order`: `RGB` 或 `BGR`。
- `invert`: 1 開啟反相，0 關閉。
- `GPIO.spi`: 使用 `spi_list` 的索引（與 APA102 設定方式相同）。
- `GPIO.dc/cs/rst`: 對應的 GPIO 腳位編號。
- `GPIO.bl`: 背光腳位；`-1` 表示不控制背光。
- `GPIO.bl_invert`: 背光邏輯反相（某些板子背光是低電位點亮）。
- `init_fill`: 1 則初始化後呼叫 `lcd.fill(0)` 清屏；0 不做。

## 註冊的 services

- `lcd`: TFT driver instance（必要）。
- `tft`: 同 `lcd`，提供另一個別名。
- `lcd_bl`: 若 `GPIO.bl >= 0` 則註冊背光 Pin 物件。

## 相關程式位置

- 初始化邏輯： [boot.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/boot.py) 的 `init_display()`
- 驅動實作： [TFT.py](file:///Users/user/Documents/code/git/mp_Net-Light/slave/lib/TFT.py)


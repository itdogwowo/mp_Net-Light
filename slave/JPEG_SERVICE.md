# JPEG Decoder Service（雙核心 + Block Decode）

## 資料流

- Core0：讀取 JPEG 檔案 → 寫入 `jpeg_in`（AtomicStreamHub）
- Core1：從 `jpeg_in` 讀取 → `jpeg.Decoder(block=True)` 逐塊解碼 → 寫入 `jpeg_blocks`（AtomicStreamHub）
- Core0：從 `jpeg_blocks` 讀取 → `lcd.set_window()` + `lcd.write_data()` 顯示

## 進入點

- [jpeg_main.py](file:///c:/Users/bl91920/Documents/code/git/mp_Net-Light/slave/jpeg_main.py)

## 需要你提供的 LCD 物件

Display 端會嘗試取得：

- `ctx["lcd"]`（如果你自行組 ctx）
- 或 `bus.register_service("lcd", lcd)`（建議）

LCD 物件需支援：

- `set_window(x0, y0, x1, y1)`
- `write_data(buf)`，其中 `buf` 是 RGB565 的 bytes/memoryview

## 設定

在 [config.json](file:///c:/Users/bl91920/Documents/code/git/mp_Net-Light/slave/config.json) 的 `JPEG` 區塊：

- `dp_config_path`：dp_config.json 路徑（用來推導 buffer 尺寸）

也可以在 runtime 更新：

- `bus.shared["jpeg_path"] = "/sd/xxx.jpg"`
- `bus.shared["jpeg_force_reload"] = True`

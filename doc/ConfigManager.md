# ConfigManager 使用指南

## 簡介

`ConfigManager` 是一個專為 MicroPython 設計的輕量級配置管理庫，旨在解決嵌入式系統中常見的設定檔維護難題。它具備以下核心特性：

1.  **無損讀取**：啟動時自動載入設定，完全保留您手動排版的格式（縮排、換行、註釋）。
2.  **密碼保護**：自動識別 `_pw` 結尾的欄位，將其值移至安全的 `secrets.db` (BTree 資料庫)，並在 JSON 文件中隱藏為空字串 `""`。
3.  **精確更新**：支援針對單一數值或結構進行「原地替換」，不破壞文件其餘部分的格式。
4.  **結構化壓縮**：當更新字典或列表時，自動將其轉為單行緊湊格式。
5.  **順序保留**：即使需要重寫文件，也會盡最大努力保留您原始的鍵值順序。

---

## 快速開始

### 1. 初始化

在您的主程式或 `boot.py` 中初始化 `ConfigManager`：

```python
from lib.sys_bus import bus
from lib.ConfigManager import ConfigManager

# 初始化並載入設定
cfg_manager = ConfigManager(bus)
cfg_manager.load_setup()
```

### 2. 讀取設定

設定值會自動載入到 `bus.shared` 中，您可以像操作普通字典一樣讀取：

```python
# 讀取系統亮度
lum = bus.shared.get("System", {}).get("c_lum", 1.0)

# 讀取 WiFi 設定 (密碼會自動從 secrets.db 填回)
ssid = bus.shared["Network"]["wifi"]["ssid"]
password = bus.shared["Network"]["wifi"]["ssid_pw"] 
```

---

## 進階操作：修改與儲存

為了保持 `config.json` 的完美格式，請遵循以下最佳實踐。

### A. 修改單一數值 (無損更新)

當您只修改一個數字、布林值或字串時：

```python
# 1. 修改記憶體中的值 (讓程式立即生效)
bus.shared["System"]["c_lum"] = 0.5

# 2. 指定路徑進行儲存 (關鍵步驟！)
# 這會精確定位並替換值，不影響周圍格式
cfg_manager.save_from_bus(update_key="System.c_lum")
```

### B. 修改字典或列表 (結構化壓縮)

當您修改一個複雜結構時，系統會自動將其轉為「單行緊湊格式」：

```python
# 假設原本是多行排版：
# "GPIO": {
#     "data": [
#         39, 40
#     ]
# }

# 1. 修改數據
bus.shared["SDcard"]["GPIO"]["data"] = [1, 2, 3, 4]

# 2. 指定路徑儲存
cfg_manager.save_from_bus(update_key="SDcard.GPIO.data")

# 3. 結果 (變緊湊了，但周圍格式不變)：
# "GPIO": {
#     "data": [1,2,3,4]
# }
```

### C. 修改密碼 (自動加密)

當您修改以 `_pw` 結尾的欄位時：

```python
bus.shared["Network"]["wifi"]["ssid_pw"] = "new_secret"

# 儲存時，系統會自動：
# 1. 將 "new_secret" 存入 secrets.db
# 2. 將 config.json 中的該欄位設為 "" (空字串)
cfg_manager.save_from_bus(update_key="Network.wifi.ssid_pw")
```

---

## 注意事項與限制

雖然我們盡力保留格式，但在以下情況，系統會被迫**重寫整個文件**（這會重置縮排為標準格式，但**保留順序**）：

1.  **未指定 `update_key`**：
    ```python
    cfg_manager.save_from_bus()  # 會觸發全檔重寫
    ```
2.  **新增了原本不存在的 Key**：
    ```python
    bus.shared["NewFeature"] = 123
    cfg_manager.save_from_bus(update_key="NewFeature") 
    # 檔案中找不到 "NewFeature" 進行替換 -> 全檔重寫
    ```
3.  **指定路徑錯誤**：
    ```python
    cfg_manager.save_from_bus(update_key="System.typo_lum")
    # 找不到路徑 -> 全檔重寫
    ```

### 總結口訣

> **「讀取隨意用，修改指定 Key」**

只要您在 `save_from_bus` 時多花一秒鐘填入 `update_key="..."`，ConfigManager 就能像外科手術一樣精確地維護您的設定檔，讓它永遠保持整潔、安全且美觀。

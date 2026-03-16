# ConfigManager 使用指南

ConfigManager 是 Slave 端用來管理 config.json 的工具，重點在：
- 盡量保留原始格式與鍵順序（減少「全檔重排」帶來的可讀性損失）
- 將敏感欄位（以 _pw 結尾）移出到 secrets.db
- 支援指定 update_key 做精準更新（避免全檔重寫）

對應實作：[ConfigManager.py](../../slave/lib/ConfigManager.py)

## 快速開始

### 初始化並載入

```python
from lib.sys_bus import bus
from lib.ConfigManager import ConfigManager

cfg_manager = ConfigManager(bus)
cfg_manager.load_setup()
```

### 讀取設定

ConfigManager 會把設定載入到 bus.shared（可依專案實際 key 讀取）：

```python
lum = bus.shared.get("System", {}).get("c_lum", 1.0)
ssid = bus.shared["Network"]["wifi"]["ssid"]
password = bus.shared["Network"]["wifi"]["ssid_pw"]
```

## 修改與儲存（重要）

### 修改單一值：指定 update_key

```python
bus.shared["System"]["c_lum"] = 0.5
cfg_manager.save_from_bus(update_key="System.c_lum")
```

### 修改結構：仍建議指定 update_key

```python
bus.shared["SDcard"]["GPIO"]["data"] = [1, 2, 3, 4]
cfg_manager.save_from_bus(update_key="SDcard.GPIO.data")
```

### 修改密碼：自動落 secrets.db

```python
bus.shared["Network"]["wifi"]["ssid_pw"] = "new_secret"
cfg_manager.save_from_bus(update_key="Network.wifi.ssid_pw")
```

## 何時會全檔重寫（盡量避免）

- 未指定 update_key
- 新增了原本不存在的 key，導致找不到可替換的原地位置
- update_key 路徑寫錯

口訣：
> 讀取隨意用，修改指定 key

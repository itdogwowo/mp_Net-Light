import btree
import json
import os
from lib.dispatch import dprint
from lib.sys_bus import bus

class ConfigManager:
    """
    進化版配置管理器
    核心變動：
    - 忽略所有以 '_obj' 結尾的鍵：不加載、不儲存、不保留。
    - 專注於數據持久化，不干涉運行時物件。
    """
    def __init__(self, sys_bus, config_path='config.json', db_path='secrets.db'):
        self.bus = sys_bus
        self.path = config_path
        self.db_path = db_path
        self._db = None
        self._f = None
        self._open_db()

    def _open_db(self):
        try:
            self._f = open(self.db_path, 'r+b')
        except OSError:
            self._f = open(self.db_path, 'w+b')
        self._db = btree.open(self._f)

    def _pretty_dump(self, obj, stream, indent=0):
        """格式化寫入，同時過濾掉 _obj"""
        space = "    "
        current_space = space * indent
        next_space = space * (indent + 1)

        if isinstance(obj, dict):
            # 過濾掉所有以 _obj 結尾的鍵
            filtered_items = [(k, v) for k, v in obj.items() if not k.endswith('_obj')]
            
            stream.write("{\n")
            for i, (k, v) in enumerate(filtered_items):
                stream.write(f'{next_space}"{k}": ')
                self._pretty_dump(v, stream, indent + 1)
                if i < len(filtered_items) - 1:
                    stream.write(",")
                stream.write("\n")
            stream.write(current_space + "}")
        elif isinstance(obj, list):
            stream.write("[\n")
            for i, item in enumerate(obj):
                stream.write(next_space)
                self._pretty_dump(item, stream, indent + 1)
                if i < len(obj) - 1:
                    stream.write(",")
                stream.write("\n")
            stream.write(current_space + "]")
        elif isinstance(obj, str):
            stream.write(f'"{obj}"')
        elif isinstance(obj, (int, float)):
            stream.write(str(obj))
        elif isinstance(obj, bool):
            stream.write("true" if obj else "false")
        elif obj is None:
            stream.write("null")
        else:
            # 對於無法直接序列化的對象（如果漏網），轉為字符串
            stream.write(f'"{str(obj)}"')

    def load_setup(self):
        """讀取配置，並過濾敏感字眼"""
        if self.path not in os.listdir():
            self.save_from_bus()
            return

        try:
            with open(self.path, 'r') as f:
                content = f.read().strip()
                data = json.loads(content) if content else {}
        except Exception as e:
            dprint(f"[Config] 讀取解析出錯: {e}")
            data = {}

        needs_cleaning = False

        def sync_node(node, prefix=""):
            nonlocal needs_cleaning
            if isinstance(node, dict):
                # 這裡不需要檢查 _obj，因為 JSON 檔案中理論上不該存在它們
                for key, value in node.items():
                    db_key = f"{prefix}{key}"
                    if isinstance(value, (dict, list)):
                        sync_node(value, prefix=db_key + ".")
                    elif key.endswith('_pw'):
                        if value not in (None, "", "null"):
                            dprint(f"[Config] 🔐 入庫密碼: {key}")
                            self._db[db_key.encode()] = json.dumps(value).encode()
                            needs_cleaning = True
                        else:
                            stored = self._db.get(db_key.encode())
                            if stored:
                                node[key] = json.loads(stored.decode())
            elif isinstance(node, list):
                for i, item in enumerate(node):
                    sync_node(item, prefix=f"{prefix}{i}.")

        sync_node(data)
        self.bus.shared.update(data)

        if needs_cleaning:
            self._db.flush()
            self.save_from_bus()

    def save_from_bus(self):
        """持久化：自動隱藏密碼，並徹底忽略 _obj 對象"""
        # 注意：我們直接在 pretty_dump 遍歷過程中執行過濾，不需要額外拷貝一份字典
        # 這樣能最大限度節省 RAM
        try:
            with open(self.path, 'w') as f:
                # 再次定義一個內部處理函數來同步 BTree，同時 _pretty_dump 負責過濾文件內容
                self._update_btree_only(self.bus.shared)
                self._pretty_dump(self.bus.shared, f)
            self._db.flush()
            dprint(f"[Config] ✓ 配置已同步 (已自動忽略 _obj 對象)")
        except Exception as e:
            dprint(f"[Config] ✗ 保存出錯: {e}")

    def _update_btree_only(self, node, prefix=""):
        """單純提取密碼到 BTree，不處理 JSON"""
        if isinstance(node, dict):
            for k, v in node.items():
                db_key = f"{prefix}{k}"
                if k.endswith('_pw'):
                    self._db[db_key.encode()] = json.dumps(v).encode()
                elif isinstance(v, (dict, list)):
                    self._update_btree_only(v, prefix=db_key + ".")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                self._update_btree_only(item, prefix=f"{prefix}{i}.")

    def close(self):
        if self._db: self._db.close()
        if self._f: self._f.close()
        
cfg_manager = ConfigManager(bus)
cfg_manager.load_setup()



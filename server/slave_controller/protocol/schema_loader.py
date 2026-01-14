# slave_controller/protocol/schema_loader.py
import json
import os

def cmd_str_to_int(s: str) -> int:
    """將 '0x1101' 轉為 int"""
    s = s.strip().lower()
    return int(s, 16) if s.startswith("0x") else int(s)

class SchemaStore:
    """載入並管理所有 schema"""
    def __init__(self):
        self.cmd_map = {}  # cmd_int -> cmd_def
        self.loaded = set()

    def load_dir(self, dir_path):
        """載入目錄下所有 .json"""
        for name in os.listdir(dir_path):
            if name.endswith(".json"):
                self.load_file(os.path.join(dir_path, name))

    def load_file(self, path: str):
        """載入單個 schema 文件"""
        if path in self.loaded:
            return
        
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if not content.strip():
            self.loaded.add(path)
            return
        
        try:
            obj = json.loads(content)
            for c in obj.get("cmds", []):
                cmd_int = cmd_str_to_int(c["cmd"])
                self.cmd_map[cmd_int] = c
            
            self.loaded.add(path)
            print(f"[Schema] 載入: {path} ({len(obj.get('cmds', []))} cmds)")
        
        except Exception as e:
            print(f"[Schema] 錯誤: {path} => {e}")
            raise

    def get(self, cmd_int: int):
        """根據 CMD 獲取定義"""
        return self.cmd_map.get(cmd_int)
    
    def get_all(self):
        """🔥 新增:獲取所有 CMD 映射"""
        return self.cmd_map
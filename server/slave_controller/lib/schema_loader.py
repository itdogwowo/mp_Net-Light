# slave_controller/lib/schema_loader.py
"""
Python 版本的 Schema Loader
"""
import json
import os

def cmd_str_to_int(s: str) -> int:
    """將 CMD 字串轉為 int (支持 0x 開頭)"""
    s = s.strip().lower()
    return int(s, 16) if s.startswith("0x") else int(s)

class SchemaStore:
    """
    載入 schema JSON 文件,建立 cmd_int -> cmd_def 的映射
    """
    def __init__(self):
        self.cmd_map = {}       # cmd_int -> cmd_def
        self.loaded = set()
    
    def load_dir(self, dir_path):
        """載入目錄下所有 .json 文件"""
        if not os.path.exists(dir_path):
            print(f"[Schema] 目錄不存在: {dir_path}")
            return
        
        for name in os.listdir(dir_path):
            if name.endswith(".json"):
                self.load_file(os.path.join(dir_path, name))
    
    def load_file(self, path: str):
        """載入單個 schema 文件"""
        if path in self.loaded:
            return
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if not content.strip():
                print(f"[Schema] 空文件,跳過: {path}")
                self.loaded.add(path)
                return
            
            obj = json.loads(content)
            
            for c in obj.get("cmds", []):
                cmd_int = cmd_str_to_int(c["cmd"])
                self.cmd_map[cmd_int] = c
                print(f"[Schema] 載入 CMD: 0x{cmd_int:04X} ({c.get('name')})")
            
            self.loaded.add(path)
            print(f"[Schema] ✅ 已載入: {path}")
            
        except json.JSONDecodeError as e:
            print(f"[Schema] ❌ JSON 解析錯誤: {path}")
            print(f"  錯誤: {e}")
            with open(path, "r") as f:
                print(f"  內容預覽: {f.read()[:200]}")
            raise
        except Exception as e:
            print(f"[Schema] ❌ 載入失敗: {path}, 錯誤: {e}")
            raise
    
    def get(self, cmd_int: int):
        """根據 CMD 獲取 cmd_def"""
        return self.cmd_map.get(cmd_int)
    
    def get_all_cmds(self):
        """獲取所有 CMD"""
        return list(self.cmd_map.keys())
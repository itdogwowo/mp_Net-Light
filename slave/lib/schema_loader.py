# /lib/schema_loader.py
import ujson as json
import os

def cmd_str_to_int(s: str) -> int:
    s = s.strip().lower()
    return int(s, 16) if s.startswith("0x") else int(s)

class SchemaStore:
    """
    載入 /schema 目錄下多個 JSON，建立 cmd_int -> cmd_def 的 map
    """
    def __init__(self):
        self.cmd_map = {}       # cmd_int -> cmd_def
        self.loaded = set()

    def load_dir(self, dir_path="/schema"):
        for name in os.listdir(dir_path):
            if name.endswith(".json"):
                self.load_file(dir_path + "/" + name)

    def load_file(self, path: str):
        if path in self.loaded:
            return
        with open(path, "r") as f:
            s = f.read()
        if not s.strip():
            # 空檔直接略過
            self.loaded.add(path)
            return

        try:
            obj = json.loads(s)
        except Exception as e:
            print("[SCHEMA JSON ERROR]", path, "=>", e)
            print("HEAD:", s[:120])
            raise

        for c in obj.get("cmds", []):
            self.cmd_map[cmd_str_to_int(c["cmd"])] = c

        self.loaded.add(path)

    def get(self, cmd_int: int):
        return self.cmd_map.get(cmd_int)
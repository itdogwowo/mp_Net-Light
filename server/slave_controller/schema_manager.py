# slave_controller/schema_manager.py
"""
Schema 管理器
- 從 Slave 下載 schema 文件
- 儲存到 /media/schemas/{slave_id}/
- 比對 schema 差異
"""
import os
import json
import hashlib
from pathlib import Path
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# 導入 Server 端 proto/schema
from slave_controller.lib.proto import pack_packet
from slave_controller.lib.schema_loader import cmd_str_to_int, SchemaStore
from slave_controller.lib.schema_codec import encode_payload

class SchemaManager:
    """Schema 管理器"""
    
    def __init__(self):
        self.base_dir = Path(settings.MEDIA_ROOT) / "schemas"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Server 端 master schema (用於對比)
        self.master_store = SchemaStore()
        master_schema_dir = Path(__file__).parent / "master_schemas"
        if master_schema_dir.exists():
            self.master_store.load_dir(str(master_schema_dir))
        
        print(f"[SchemaManager] 初始化完成,儲存路徑: {self.base_dir}")
    
    def get_slave_schema_dir(self, slave_id: str) -> Path:
        """獲取 Slave 的 schema 目錄"""
        slave_dir = self.base_dir / slave_id
        slave_dir.mkdir(parents=True, exist_ok=True)
        return slave_dir
    
    def download_schema_from_slave(self, slave_id: str, schema_name: str):
        """
        從 Slave 下載單個 schema 文件
        使用 FS_SNAP_GET + FILE 三件套
        
        步驟:
        1. 發送 FS_SNAP_GET 請求 /schema/{schema_name}.json
        2. Slave 回傳 FILE_BEGIN/CHUNK/END
        3. 儲存到 /media/schemas/{slave_id}/{schema_name}.json
        """
        print(f"[SchemaManager] 請求下載 schema: {slave_id}/{schema_name}")
        
        # 🔥 構造 FS_SNAP_GET 指令
        CMD_FS_SNAP_GET = cmd_str_to_int("0x1213")
        
        # 從 master schema 獲取 cmd_def
        cmd_def = self.master_store.get(CMD_FS_SNAP_GET)
        if not cmd_def:
            print("[SchemaManager] ❌ FS_SNAP_GET schema 未找到")
            return False
        
        # 編碼 payload
        payload = encode_payload(cmd_def, {
            "path": f"/schema/{schema_name}.json",
            "out_path": f"/tx_{schema_name}.json",  # Slave 端暫存路徑
            "max_depth": 1,
            "include_size": 0
        })
        
        packet = pack_packet(CMD_FS_SNAP_GET, payload)
        
        # 🔥 通過 WebSocket 發送
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"slave_{slave_id}",
            {
                "type": "send_cmd",
                "packet": packet
            }
        )
        
        print(f"[SchemaManager] ✅ 已發送 FS_SNAP_GET 到 {slave_id}")
        return True
    
    def save_schema_file(self, slave_id: str, schema_name: str, content: bytes):
        """儲存下載的 schema 文件"""
        slave_dir = self.get_slave_schema_dir(slave_id)
        file_path = slave_dir / f"{schema_name}.json"
        
        try:
            # 驗證 JSON 格式
            json.loads(content.decode('utf-8'))
            
            # 儲存
            with open(file_path, 'wb') as f:
                f.write(content)
            
            print(f"[SchemaManager] ✅ 已儲存 schema: {file_path}")
            return True
            
        except json.JSONDecodeError as e:
            print(f"[SchemaManager] ❌ JSON 格式錯誤: {e}")
            return False
        except Exception as e:
            print(f"[SchemaManager] ❌ 儲存失敗: {e}")
            return False
    
    def load_slave_schemas(self, slave_id: str) -> SchemaStore:
        """載入 Slave 的所有 schema"""
        slave_dir = self.get_slave_schema_dir(slave_id)
        
        store = SchemaStore()
        store.load_dir(str(slave_dir))
        
        return store
    
    def compare_schemas(self, slave_id: str) -> dict:
        """
        比對 Slave 與 Master schema
        返回差異報告
        """
        slave_store = self.load_slave_schemas(slave_id)
        
        master_cmds = set(self.master_store.get_all_cmds())
        slave_cmds = set(slave_store.get_all_cmds())
        
        # 計算差異
        missing_in_slave = master_cmds - slave_cmds
        extra_in_slave = slave_cmds - master_cmds
        common_cmds = master_cmds & slave_cmds
        
        # 檢查 payload 差異
        payload_diff = []
        for cmd in common_cmds:
            master_def = self.master_store.get(cmd)
            slave_def = slave_store.get(cmd)
            
            if master_def != slave_def:
                payload_diff.append({
                    "cmd": f"0x{cmd:04X}",
                    "name": master_def.get("name"),
                    "master": master_def,
                    "slave": slave_def
                })
        
        return {
            "slave_id": slave_id,
            "missing_in_slave": [f"0x{c:04X}" for c in missing_in_slave],
            "extra_in_slave": [f"0x{c:04X}" for c in extra_in_slave],
            "payload_diff": payload_diff,
            "is_synced": len(missing_in_slave) == 0 and len(payload_diff) == 0
        }

# 全局單例
schema_manager = SchemaManager()
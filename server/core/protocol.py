# server/core/protocol.py
from django.conf import settings
from lib.proto import Proto, StreamParser 
from lib.schema_loader import SchemaStore
from lib.schema_codec import SchemaCodec 
import logging

logger = logging.getLogger(__name__)

class ProtocolManager:
    def __init__(self):
        self.schema_dir = settings.PROTOCOL_CONFIG['schema_dir']
        # 1. 初始化你的 SchemaStore
        self.store = SchemaStore(dir_path=self.schema_dir)
        
        # 2. 修正：建立內部快速索引，並確保 cmd_int 存在
        # 因為你的 SchemaStore.cmd_map 已經是 {int: dict}，我們直接對齊它
        self.cmd_map = {}
        for cmd_id, cmd_def in self.store.cmd_map.items():
            # 強制注入 cmd_int 方便後續 pack 使用
            cmd_def['cmd_int'] = cmd_id 
            self.cmd_map[cmd_id] = cmd_def
        
        logger.info(f"✓ Protocol initialized. Loaded {len(self.cmd_map)} commands.")

    def pack(self, cmd_hex_or_int, data_dict):
        """將字典數據打包成 NL 封包"""
        # 支援 "0x1101" 轉 int
        if isinstance(cmd_hex_or_int, str) and "0x" in cmd_hex_or_int:
            cmd_id = int(cmd_hex_or_int, 16)
        else:
            cmd_id = int(cmd_hex_or_int)

        # 從我們修正過的 cmd_map 拿
        cmd_def = self.cmd_map.get(cmd_id)
        if not cmd_def:
            raise ValueError(f"Unknown command: {cmd_hex_or_int}")
        
        # 使用你的 SchemaCodec.encode
        payload = SchemaCodec.encode(cmd_def, data_dict)
        
        # 使用你的 Proto.pack
        return Proto.pack(cmd=cmd_id, payload=payload)

    def unpack(self, cmd_int, payload_bytes):
        """將二進位解析為字典"""
        cmd_def = self.cmd_map.get(cmd_int)
        if not cmd_def:
            return None, payload_bytes
        
        # 使用你的 SchemaCodec.decode
        # 注意：你的 decode 會自動加上 _name 和 _cmd
        decoded_args = SchemaCodec.decode(cmd_def, payload_bytes)
        return cmd_def['name'], decoded_args

# 單例化
proto_mgr = ProtocolManager()
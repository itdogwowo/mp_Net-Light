# slave_controller/consumers.py (完整版 - 支援 FILE 接收 + 燈效廣播)
import asyncio
import struct
from channels.generic.websocket import AsyncWebsocketConsumer
from datetime import datetime
from pathlib import Path
from django.conf import settings

# 🔥 導入 Server 端 proto/schema (需要先創建這些文件)
# from slave_controller.lib.proto import StreamParser
# from slave_controller.lib.schema_loader import cmd_str_to_int, SchemaStore
# from slave_controller.lib.schema_codec import decode_payload

class SlaveConsumer(AsyncWebsocketConsumer):
    """
    Slave WebSocket Consumer - 處理 CMD 二進位協議
    支援:
    - CMD 封包解析 (使用 StreamParser)
    - FILE 三件套接收
    - 燈效幀廣播
    """
    
    # 🔥 全局 Slave 房間組 (用於燈效廣播)
    SLAVE_GROUP = "all_slaves"
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parser = None  # StreamParser 實例 (暫時不用,等 lib 完成)
        self.file_receiver = None  # FILE 接收器
    
    async def connect(self):
        """Slave 連接"""
        self.slave_id = self.scope['url_route']['kwargs'].get('slave_id')
        self.room_group_name = f'slave_{self.slave_id}'
        
        print("=" * 50)
        print(f"[SlaveWS] Slave {self.slave_id} 嘗試連接")
        
        # 🔥 加入個人房間
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # 🔥 加入全局廣播組
        await self.channel_layer.group_add(
            self.SLAVE_GROUP,
            self.channel_name
        )
        
        # 🔥 初始化 FILE 接收器
        self.file_receiver = FileReceiver(self.slave_id)
        
        await self.accept()
        
        print(f"[SlaveWS] ✅ Slave {self.slave_id} WebSocket 已連接")
        print(f"[SlaveWS] ✅ 已加入廣播組: {self.SLAVE_GROUP}")
        print("=" * 50)
    
    async def disconnect(self, close_code):
        """Slave 斷開"""
        print(f"[SlaveWS] Slave {self.slave_id} WebSocket 已斷開 (code: {close_code})")
        
        # 離開個人房間
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        # 🔥 離開廣播組
        await self.channel_layer.group_discard(
            self.SLAVE_GROUP,
            self.channel_name
        )
    
    async def receive(self, text_data=None, bytes_data=None):
        """接收消息"""
        if bytes_data:
            # 🔥 暫時使用簡單解析 (等 StreamParser 完成後替換)
            await self._handle_cmd_packet_simple(bytes_data)
        elif text_data:
            print(f"[SlaveWS] 收到文本: {text_data[:100]}")
    
    async def _handle_cmd_packet_simple(self, packet):
        """
        處理 CMD 封包 (簡化版,不使用 StreamParser)
        🔥 完整版應使用 StreamParser.feed() + pop()
        """
        if len(packet) < 11:
            return
        
        sof = packet[0:2]
        if sof != b'NL':
            return
        
        cmd = struct.unpack('<H', packet[5:7])[0]
        length = struct.unpack('<H', packet[7:9])[0]
        
        print(f"[SlaveWS] 📥 收到 CMD: 0x{cmd:04X}, LEN: {length}")
        
        # 提取 payload
        payload = packet[9:9+length]
        
        # 根據 CMD 處理
        if cmd == 0x1102:  # STATUS_RSP
            await self._handle_status_rsp(payload)
        elif cmd == 0x1104:  # STATUS_UPDATE_ACK
            await self._handle_status_update_ack(payload)
        elif cmd == 0x2001:  # FILE_BEGIN
            await self._handle_file_begin(payload)
        elif cmd == 0x2002:  # FILE_CHUNK
            await self._handle_file_chunk(payload)
        elif cmd == 0x2003:  # FILE_END
            await self._handle_file_end(payload)
        elif cmd == 0x3004:  # STREAM_STATUS
            await self._handle_stream_status(payload)
    
    # ==================== STATUS 指令處理 ====================
    
    async def _handle_status_rsp(self, payload):
        """處理 STATUS_RSP"""
        try:
            str_len = struct.unpack('<H', payload[0:2])[0]
            status_json = payload[2:2+str_len].decode('utf-8')
            
            print(f"[SlaveWS] 📊 STATUS_RSP: {status_json[:100]}...")
            
            # 發送到前端 (通過 WebSocket)
            await self.send(text_data=status_json)
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 STATUS_RSP 錯誤: {e}")
    
    async def _handle_status_update_ack(self, payload):
        """處理 STATUS_UPDATE_ACK"""
        try:
            success = payload[0]
            str_len = struct.unpack('<H', payload[1:3])[0]
            message = payload[3:3+str_len].decode('utf-8')
            
            print(f"[SlaveWS] ✅ STATUS_UPDATE_ACK: success={success}, msg={message}")
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理錯誤: {e}")
    
    # ==================== FILE 三件套處理 ====================
    
    async def _handle_file_begin(self, payload):
        """處理 FILE_BEGIN"""
        try:
            # 簡化解析 (完整版應使用 schema_codec)
            file_id = struct.unpack('<I', payload[0:4])[0]
            total_size = struct.unpack('<I', payload[4:8])[0]
            chunk_size = struct.unpack('<H', payload[8:10])[0]
            sha256 = payload[10:42]
            
            str_len = struct.unpack('<H', payload[42:44])[0]
            path = payload[44:44+str_len].decode('utf-8')
            
            args = {
                "file_id": file_id,
                "total_size": total_size,
                "chunk_size": chunk_size,
                "sha256": sha256,
                "path": path
            }
            
            ok = await self.file_receiver.begin(args)
            
            if ok:
                print(f"[SlaveWS] 📥 FILE_BEGIN: {path} ({total_size} bytes)")
            else:
                print(f"[SlaveWS] ❌ FILE_BEGIN 失敗: {self.file_receiver.last_error}")
                
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 FILE_BEGIN 錯誤: {e}")
            import traceback
            traceback.print_exc()
    
    async def _handle_file_chunk(self, payload):
        """處理 FILE_CHUNK"""
        try:
            file_id = struct.unpack('<I', payload[0:4])[0]
            offset = struct.unpack('<I', payload[4:8])[0]
            data = payload[8:]
            
            args = {
                "file_id": file_id,
                "offset": offset,
                "data": data
            }
            
            ok = await self.file_receiver.chunk(args)
            
            if not ok:
                print(f"[SlaveWS] ❌ FILE_CHUNK 失敗: {self.file_receiver.last_error}")
                
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 FILE_CHUNK 錯誤: {e}")
    
    async def _handle_file_end(self, payload):
        """處理 FILE_END"""
        try:
            file_id = struct.unpack('<I', payload[0:4])[0]
            
            args = {"file_id": file_id}
            
            ok = await self.file_receiver.end(args)
            
            if ok:
                print(f"[SlaveWS] ✅ FILE_END: 文件接收完成")
                
                # 🔥 如果是 schema 文件,觸發特殊處理
                if self.file_receiver.is_schema_file():
                    await self._save_received_schema()
            else:
                print(f"[SlaveWS] ❌ FILE_END 失敗: {self.file_receiver.last_error}")
                
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理 FILE_END 錯誤: {e}")
    
    async def _save_received_schema(self):
        """儲存接收到的 schema 文件"""
        try:
            schema_name = self.file_receiver.get_schema_name()
            file_path = self.file_receiver.path
            
            # 讀取文件內容
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # 🔥 儲存到 schema_manager (需要實現)
            # from slave_controller.schema_manager import schema_manager
            # schema_manager.save_schema_file(self.slave_id, schema_name, content)
            
            print(f"[SlaveWS] ✅ 已儲存 schema: {schema_name}")
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 儲存 schema 失敗: {e}")
    
    # ==================== STREAM 指令處理 ====================
    
    async def _handle_stream_status(self, payload):
        """處理 STREAM_STATUS"""
        try:
            is_playing = payload[0]
            current_frame = struct.unpack('<I', payload[1:5])[0]
            dropped_frames = struct.unpack('<H', payload[5:7])[0]
            
            print(f"[SlaveWS] 📊 STREAM_STATUS: playing={is_playing}, frame={current_frame}, dropped={dropped_frames}")
            
        except Exception as e:
            print(f"[SlaveWS] ❌ 處理錯誤: {e}")
    
    # ==================== Channel Layer 消息處理 ====================
    
    async def send_cmd(self, event):
        """
        從 channel layer 接收並發送 CMD 封包
        用於單播 (個人房間)
        """
        packet = event.get('packet')
        if packet:
            await self.send(bytes_data=packet)
            # print(f"[SlaveWS] 📤 已發送 CMD: {len(packet)} bytes")
    
    async def broadcast_frame(self, event):
        """
        接收廣播的燈效幀並發送
        用於廣播 (all_slaves 房間)
        性能優化:不打印日誌
        """
        packet = event.get('packet')
        if packet:
            await self.send(bytes_data=packet)


# ==================== FILE 接收器 ====================

class FileReceiver:
    """
    文件接收器 (移植自 MicroPython /lib/file_rx.py)
    處理 FILE_BEGIN/CHUNK/END 三件套
    """
    
    def __init__(self, slave_id: str):
        self.slave_id = slave_id
        self.reset()
    
    def reset(self):
        self.active = False
        self.file_id = 0
        self.total = 0
        self.chunk_size = 0
        self.sha_expect = None
        self.path = None
        self.fp = None
        self.written = 0
        self.last_error = None
    
    async def begin(self, args: dict) -> bool:
        """開始接收文件"""
        self.last_error = None
        self._close()
        self.reset()
        
        self.active = True
        self.file_id = int(args["file_id"])
        self.total = int(args["total_size"])
        self.chunk_size = int(args["chunk_size"])
        self.sha_expect = args["sha256"]
        
        # 🔥 儲存到臨時目錄
        temp_dir = Path(settings.MEDIA_ROOT) / "temp" / self.slave_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        filename = args["path"].split("/")[-1]
        self.path = str(temp_dir / filename)
        
        self.written = 0
        
        try:
            # 預分配文件
            with open(self.path, "wb") as f:
                if self.total > 0:
                    f.seek(self.total - 1)
                    f.write(b"\x00")
            
            self.fp = open(self.path, "r+b")
            return True
            
        except Exception as e:
            self.last_error = f"OPEN_FAIL: {e}"
            self.active = False
            return False
    
    async def chunk(self, args: dict) -> bool:
        """接收文件塊"""
        if not self.active or self.fp is None:
            self.last_error = "NO_ACTIVE"
            return False
        
        if int(args["file_id"]) != self.file_id:
            self.last_error = "FILE_ID_MISMATCH"
            return False
        
        offset = int(args["offset"])
        data = args["data"] or b""
        
        if offset + len(data) > self.total:
            self.last_error = "OUT_OF_RANGE"
            return False
        
        try:
            self.fp.seek(offset)
            self.fp.write(data)
            self.written += len(data)
            return True
        except Exception as e:
            self.last_error = f"WRITE_FAIL: {e}"
            return False
    
    async def end(self, args: dict) -> bool:
        """結束接收"""
        if int(args["file_id"]) != self.file_id:
            self.last_error = "FILE_ID_MISMATCH"
            return False
        
        self._close()
        
        # 驗證 SHA256
        import hashlib
        sha = hashlib.sha256()
        
        with open(self.path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha.update(chunk)
        
        got = sha.digest()
        ok = (got == self.sha_expect)
        
        if not ok:
            self.last_error = f"SHA_MISMATCH: expected {self.sha_expect.hex()}, got {got.hex()}"
        
        self.active = False
        return ok
    
    def _close(self):
        if self.fp:
            try:
                self.fp.close()
            except Exception:
                pass
        self.fp = None
    
    def is_schema_file(self) -> bool:
        """判斷是否為 schema 文件"""
        return self.path and self.path.endswith(".json") and "schema" in self.path.lower()
    
    def get_schema_name(self) -> str:
        """獲取 schema 名稱"""
        if self.path:
            return Path(self.path).stem
        return ""
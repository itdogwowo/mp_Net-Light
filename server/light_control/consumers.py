# light_control/consumers.py - 支援廣播和監察
import json
import asyncio
import base64
from channels.generic.websocket import AsyncWebsocketConsumer
from pathlib import Path
from django.conf import settings
from datetime import datetime

class LightControlConsumer(AsyncWebsocketConsumer):
    """
    燈效控制 WebSocket Consumer
    支援兩種模式：
    1. 播放模式（playback）：執行播放並廣播到房間
    2. 監察模式（monitor）：只接收廣播，不發送控制訊息
    """
    
    async def connect(self):
        """客戶端連接"""
        print("=" * 50)
        print("[WebSocket] 新連接請求")
        
        # 從 URL 獲取設備 ID 和模式
        self.device_id = self.scope['url_route']['kwargs'].get('device_id', 'playback')
        self.mode = self.scope['url_route']['kwargs'].get('mode', 'player')  # player or monitor
        
        # 房間名稱（所有播放器和監察器共享同一個房間）
        self.room_group_name = 'playback_room'
        
        print(f"[WebSocket] device_id: {self.device_id}, mode: {self.mode}")
        print(f"[WebSocket] room: {self.room_group_name}")
        
        # 加入房間組
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # 播放相關屬性（只有 player 模式需要）
        self.playback_task = None
        self.playing = False
        self.current_frame = 0
        self.total_frames = 0
        self.fps = 30
        self.decoder = None
        self.filename = None
        self.slave_id = -1
        self.all_slave_ids = []
        
        await self.accept()
        
        # 發送歡迎消息（廣播到房間）
        await self.broadcast_to_room({
            'type': 'connection',
            'message': f'{self.mode.upper()} connected to mp_Net-Light Server',
            'device_id': self.device_id,
            'mode': self.mode,
            'timestamp': datetime.now().isoformat(),
        })
        
        print(f"[WebSocket] {self.device_id} ({self.mode}) 連接完成")
        print("=" * 50)
    
    async def disconnect(self, close_code):
        """客戶端斷開"""
        print(f"[WebSocket] 斷開連接: {self.device_id} ({self.mode}), code: {close_code}")
        
        # 廣播斷開訊息
        await self.broadcast_to_room({
            'type': 'disconnection',
            'message': f'{self.mode.upper()} disconnected',
            'device_id': self.device_id,
            'mode': self.mode,
            'timestamp': datetime.now().isoformat(),
        })
        
        await self.stop_playback()
        
        # 離開房間組
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """接收客戶端消息"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            print(f"[WebSocket] {self.device_id} ({self.mode}) 接收: {message_type}")
            
            # 監察模式只接收，不處理控制訊息
            if self.mode == 'monitor':
                await self.broadcast_to_room({
                    'type': 'monitor_message',
                    'message': f'Monitor 嘗試發送訊息（已忽略）: {message_type}',
                    'original_data': data,
                    'timestamp': datetime.now().isoformat(),
                })
                return
            
            # 廣播接收到的訊息（讓監察器可以看到）
            await self.broadcast_to_room({
                'type': 'client_message',
                'message': f'客戶端發送: {message_type}',
                'device_id': self.device_id,
                'data': data,
                'timestamp': datetime.now().isoformat(),
            })
            
            # 處理播放控制訊息
            if message_type == 'playback_init':
                await self.init_playback(data)
            elif message_type == 'playback_play':
                await self.start_playback(data)
            elif message_type == 'playback_pause':
                await self.pause_playback()
            elif message_type == 'playback_stop':
                await self.stop_playback()
            elif message_type == 'playback_seek':
                await self.seek_frame(data)
            elif message_type == 'playback_get_frame':
                await self.get_single_frame(data)
            else:
                await self.broadcast_to_room({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}',
                    'device_id': self.device_id,
                })
        
        except json.JSONDecodeError:
            await self.broadcast_to_room({
                'type': 'error',
                'message': 'Invalid JSON format',
                'device_id': self.device_id,
            })
        except Exception as e:
            print(f"[WebSocket] 錯誤: {e}")
            import traceback
            traceback.print_exc()
            await self.broadcast_to_room({
                'type': 'error',
                'message': f'Server error: {str(e)}',
                'device_id': self.device_id,
            })
    
    # ==================== 房間廣播方法 ====================
    
    async def broadcast_to_room(self, message_dict):
        """廣播訊息到房間（所有連接的客戶端都會收到）"""
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'room_message',
                'message': message_dict
            }
        )
    
    async def room_message(self, event):
        """接收房間廣播的訊息並發送給客戶端"""
        message = event['message']
        await self.send(text_data=json.dumps(message))
    
    # ==================== 播放控制方法 ====================
    
    async def init_playback(self, data):
        """初始化播放器"""
        print("[Playback] 初始化播放器...")
        
        self.filename = data.get('filename', 'show.pxld')
        self.slave_id = data.get('slave_id', -1)
        
        try:
            from .pxld_v3_decoder_api import PXLDv3DecoderAPI
            from .pxld_v3_decoder import PXLDv3
            
            filepath = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / self.filename
            
            if not filepath.exists():
                raise FileNotFoundError(f"PXLD 文件不存在: {filepath}")
            
            self.decoder = PXLDv3DecoderAPI(str(filepath))
            
            # 獲取所有 slave ID
            pxld = PXLDv3(str(filepath))
            slaves = pxld.get_frame0_slaves()
            self.all_slave_ids = [s.slave_id for s in slaves]
            
            self.fps = self.decoder.fh.fps
            self.total_frames = self.decoder.fh.total_frames
            
            # 廣播就緒訊息
            await self.broadcast_to_room({
                'type': 'playback_ready',
                'fps': self.fps,
                'total_frames': self.total_frames,
                'total_slaves': self.decoder.fh.total_slaves,
                'slave_ids': self.all_slave_ids,
                'filename': self.filename,
                'device_id': self.device_id,
            })
            
            print("[Playback] 初始化成功")
            
        except Exception as e:
            print(f"[Playback] 初始化失敗: {e}")
            import traceback
            traceback.print_exc()
            
            await self.broadcast_to_room({
                'type': 'playback_error',
                'message': f'Failed to load PXLD file: {str(e)}',
                'device_id': self.device_id,
            })
    
    async def start_playback(self, data):
        """開始播放"""
        if not self.decoder:
            await self.broadcast_to_room({
                'type': 'playback_error',
                'message': 'Playback not initialized',
                'device_id': self.device_id,
            })
            return
        
        if self.playback_task:
            self.playback_task.cancel()
        
        self.playing = True
        start_frame = data.get('frame', 0)
        self.current_frame = start_frame
        
        self.playback_task = asyncio.create_task(self.playback_loop())
        
        await self.broadcast_to_room({
            'type': 'playback_started',
            'frame': self.current_frame,
            'fps': self.fps,
            'device_id': self.device_id,
        })
    
    async def playback_loop(self):
        """播放循環"""
        frame_time = 1.0 / self.fps
        
        try:
            while self.playing and self.current_frame < self.total_frames:
                start_time = asyncio.get_event_loop().time()
                
                # 發送當前幀（廣播）
                await self.send_frame_data(self.current_frame)
                
                # 更新幀號
                self.current_frame += 1
                if self.current_frame >= self.total_frames:
                    self.current_frame = 0
                
                # 計算等待時間
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_time = max(0, frame_time - elapsed)
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
        
        except asyncio.CancelledError:
            print("[Playback] 播放任務被取消")
        except Exception as e:
            print(f"[Playback] 播放循環錯誤: {e}")
    
    async def pause_playback(self):
        """暫停播放"""
        self.playing = False
        await self.broadcast_to_room({
            'type': 'playback_paused',
            'frame': self.current_frame,
            'device_id': self.device_id,
        })
    
    async def stop_playback(self):
        """停止播放"""
        self.playing = False
        self.current_frame = 0
        
        if self.playback_task:
            self.playback_task.cancel()
            try:
                await self.playback_task
            except asyncio.CancelledError:
                pass
            self.playback_task = None
        
        await self.broadcast_to_room({
            'type': 'playback_stopped',
            'device_id': self.device_id,
        })
    
    async def seek_frame(self, data):
        """跳轉到指定幀"""
        frame = max(0, min(data.get('frame', 0), self.total_frames - 1))
        self.current_frame = frame
        await self.send_frame_data(frame)
    
    async def get_single_frame(self, data):
        """獲取單個幀數據"""
        frame = data.get('frame', 0)
        slave_id = data.get('slave_id', self.slave_id)
        await self.send_frame_data(frame, slave_id)
    
    async def send_frame_data(self, frame, slave_id=None):
        """
        發送幀數據（廣播到房間）
        如果 slave_id == -1，發送所有 slave 的數據（總畫板模式）
        """
        if not self.decoder:
            return
        
        if slave_id is None:
            slave_id = self.slave_id
        
        try:
            if slave_id == -1:
                # 總畫板模式：發送所有 slave 的數據
                slaves_data = []
                
                for sid in self.all_slave_ids:
                    try:
                        rgbw_bytes = self.decoder.get_slave_rgbw_bytes(frame, sid)
                        rgbw_base64 = base64.b64encode(rgbw_bytes).decode('ascii')
                        
                        slaves_data.append({
                            'slave_id': sid,
                            'rgbw_b64': rgbw_base64
                        })
                    except Exception as e:
                        print(f"[Playback] 獲取 Slave {sid} 數據失敗: {e}")
                
                # 廣播所有 slave 的數據
                await self.broadcast_to_room({
                    'type': 'frame_data_all',
                    'frame': frame,
                    'slaves': slaves_data,
                    'device_id': self.device_id,
                    'timestamp': datetime.now().isoformat()
                })
                
            else:
                # 單個 slave 模式
                rgbw_bytes = self.decoder.get_slave_rgbw_bytes(frame, slave_id)
                rgbw_base64 = base64.b64encode(rgbw_bytes).decode('ascii')
                
                await self.broadcast_to_room({
                    'type': 'frame_data',
                    'frame': frame,
                    'slave_id': slave_id,
                    'rgbw_b64': rgbw_base64,
                    'device_id': self.device_id,
                    'timestamp': datetime.now().isoformat()
                })
            
        except Exception as e:
            print(f"[Playback] 獲取幀數據錯誤: {e}")
            await self.broadcast_to_room({
                'type': 'playback_error',
                'message': f'Error getting frame {frame}: {str(e)}',
                'device_id': self.device_id,
            })
# light_control/consumers.py（簡化版本）
import json
import asyncio
import base64
from channels.generic.websocket import AsyncWebsocketConsumer
from pathlib import Path
from django.conf import settings

class LightControlConsumer(AsyncWebsocketConsumer):
    """燈效控制 WebSocket Consumer（簡化播放版）"""
    
    async def connect(self):
        """客戶端連接"""
        # 從 URL 獲取設備 ID
        self.device_id = self.scope['url_route']['kwargs'].get('device_id', 'playback')
        
        # 播放相關屬性
        self.playback_mode = (self.device_id == 'playback')
        self.playback_task = None
        self.playing = False
        self.current_frame = 0
        self.total_frames = 0
        self.fps = 30
        self.decoder = None
        self.filename = None
        self.slave_id = -1
        
        # 接受連接
        await self.accept()
        
        # 發送歡迎消息
        await self.send_message({
            'type': 'connection',
            'message': 'Connected to mp_Net-Light Server',
            'device_id': self.device_id,
            'timestamp': datetime.now().isoformat(),
        })
        
        print(f"[WebSocket] Connected: {self.device_id}")
    
    async def disconnect(self, close_code):
        """客戶端斷開"""
        # 停止播放
        await self.stop_playback()
        
        print(f"[WebSocket] Disconnected: {self.device_id} code {close_code}")
    
    async def receive(self, text_data):
        """接收客戶端消息"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            print(f"[WebSocket] Received from {self.device_id}: {message_type}")
            
            # 只處理播放相關消息
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
                await self.send_message({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                })
        
        except json.JSONDecodeError:
            await self.send_message({
                'type': 'error',
                'message': 'Invalid JSON format'
            })
        except Exception as e:
            await self.send_message({
                'type': 'error',
                'message': f'Server error: {str(e)}'
            })
    
    # ==================== 播放控制方法 ====================
    
    async def init_playback(self, data):
        """初始化播放器"""
        self.filename = data.get('filename', 'show.pxld')
        self.slave_id = data.get('slave_id', -1)
        
        # 獲取解碼器
        from .pxld_v3_decoder_api import PXLDv3DecoderAPI
        filepath = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / self.filename
        self.decoder = PXLDv3DecoderAPI(str(filepath))
        
        if not self.decoder or not self.decoder.fh:
            await self.send_message({
                'type': 'playback_error',
                'message': f'Failed to load PXLD file: {self.filename}'
            })
            return
        
        # 設置播放參數
        self.fps = self.decoder.fh.fps
        self.total_frames = self.decoder.fh.total_frames
        
        await self.send_message({
            'type': 'playback_ready',
            'fps': self.fps,
            'total_frames': self.total_frames,
            'total_slaves': self.decoder.fh.total_slaves,
            'filename': self.filename
        })
        
        print(f"[Playback] Initialized: {self.filename}, {self.total_frames} frames @ {self.fps}fps")
    
    async def start_playback(self, data):
        """開始播放"""
        if not self.decoder:
            await self.send_message({
                'type': 'playback_error',
                'message': 'Playback not initialized'
            })
            return
        
        # 停止現有播放任務
        if self.playback_task:
            self.playback_task.cancel()
        
        self.playing = True
        start_frame = data.get('frame', 0)
        self.current_frame = start_frame
        
        # 創建播放任務
        self.playback_task = asyncio.create_task(self.playback_loop())
        
        await self.send_message({
            'type': 'playback_started',
            'frame': self.current_frame,
            'fps': self.fps
        })
    
    async def playback_loop(self):
        """播放循環"""
        frame_time = 1.0 / self.fps
        
        try:
            while self.playing and self.current_frame < self.total_frames:
                start_time = asyncio.get_event_loop().time()
                
                # 發送當前幀
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
                else:
                    # 如果處理時間超過了幀時間，跳過一些幀以保持同步
                    skip_frames = int(elapsed / frame_time)
                    if skip_frames > 0:
                        self.current_frame += skip_frames
                        if self.current_frame >= self.total_frames:
                            self.current_frame %= self.total_frames
        except asyncio.CancelledError:
            # 任務被取消，正常退出
            pass
        except Exception as e:
            print(f"[Playback] Error in playback loop: {e}")
            await self.send_message({
                'type': 'playback_error',
                'message': f'Playback error: {str(e)}'
            })
    
    async def pause_playback(self):
        """暫停播放"""
        self.playing = False
        await self.send_message({
            'type': 'playback_paused',
            'frame': self.current_frame
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
        
        await self.send_message({
            'type': 'playback_stopped'
        })
    
    async def seek_frame(self, data):
        """跳轉到指定幀"""
        frame = max(0, min(data.get('frame', 0), self.total_frames - 1))
        self.current_frame = frame
        
        # 發送該幀的數據
        await self.send_frame_data(frame)
    
    async def get_single_frame(self, data):
        """獲取單個幀數據"""
        frame = data.get('frame', 0)
        slave_id = data.get('slave_id', self.slave_id)
        
        await self.send_frame_data(frame, slave_id)
    
    async def send_frame_data(self, frame, slave_id=None):
        """發送幀數據"""
        if not self.decoder:
            return
        
        if slave_id is None:
            slave_id = self.slave_id
        
        try:
            # 獲取幀數據
            rgbw_bytes = self.decoder.get_slave_rgbw_bytes(frame, slave_id)
            rgbw_base64 = base64.b64encode(rgbw_bytes).decode('ascii')
            
            # 發送消息
            await self.send_message({
                'type': 'frame_data',
                'frame': frame,
                'slave_id': slave_id,
                'rgbw_b64': rgbw_base64,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            await self.send_message({
                'type': 'playback_error',
                'message': f'Error getting frame {frame}: {str(e)}'
            })
    
    # ==================== 工具方法 ====================
    
    async def send_message(self, data):
        """發送 JSON 消息的包裝方法"""
        await self.send(text_data=json.dumps(data))
# light_control/consumers.py - 添加詳細日誌
import json
import asyncio
import base64
from channels.generic.websocket import AsyncWebsocketConsumer
from pathlib import Path
from django.conf import settings
from datetime import datetime

class LightControlConsumer(AsyncWebsocketConsumer):
    """燈效控制 WebSocket Consumer（帶詳細日誌）"""
    
    async def connect(self):
        """客戶端連接"""
        print("=" * 50)
        print("[WebSocket] 新連接請求")
        
        # 從 URL 獲取設備 ID
        self.device_id = self.scope['url_route']['kwargs'].get('device_id', 'playback')
        print(f"[WebSocket] device_id: {self.device_id}")
        
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
        print("[WebSocket] 接受連接...")
        await self.accept()
        print("[WebSocket] 連接已接受")
        
        try:
            # 發送歡迎消息
            welcome_msg = {
                'type': 'connection',
                'message': 'Connected to mp_Net-Light Server',
                'device_id': self.device_id,
                'timestamp': datetime.now().isoformat(),
            }
            print(f"[WebSocket] 發送歡迎訊息: {welcome_msg}")
            await self.send(text_data=json.dumps(welcome_msg))
            print("[WebSocket] 歡迎訊息已發送")
        except Exception as e:
            print(f"[WebSocket] 發送歡迎訊息時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"[WebSocket] {self.device_id} 連接完成")
        print("=" * 50)
    
    async def disconnect(self, close_code):
        """客戶端斷開"""
        print("=" * 50)
        print(f"[WebSocket] 斷開連接: {self.device_id}")
        print(f"[WebSocket] Close code: {close_code}")
        
        # 停止播放
        try:
            await self.stop_playback()
        except Exception as e:
            print(f"[WebSocket] 停止播放時發生錯誤: {e}")
        
        print(f"[WebSocket] {self.device_id} 已斷開")
        print("=" * 50)
    
    async def receive(self, text_data):
        """接收客戶端消息"""
        print("=" * 50)
        print(f"[WebSocket] 接收到訊息: {text_data[:100]}...")
        
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            print(f"[WebSocket] 訊息類型: {message_type}")
            
            # 只處理播放相關消息
            if message_type == 'playback_init':
                print("[WebSocket] 處理: playback_init")
                await self.init_playback(data)
            elif message_type == 'playback_play':
                print("[WebSocket] 處理: playback_play")
                await self.start_playback(data)
            elif message_type == 'playback_pause':
                print("[WebSocket] 處理: playback_pause")
                await self.pause_playback()
            elif message_type == 'playback_stop':
                print("[WebSocket] 處理: playback_stop")
                await self.stop_playback()
            elif message_type == 'playback_seek':
                print("[WebSocket] 處理: playback_seek")
                await self.seek_frame(data)
            elif message_type == 'playback_get_frame':
                print("[WebSocket] 處理: playback_get_frame")
                await self.get_single_frame(data)
            else:
                print(f"[WebSocket] 未知訊息類型: {message_type}")
                await self.send_message({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                })
        
        except json.JSONDecodeError as e:
            print(f"[WebSocket] JSON 解析錯誤: {e}")
            await self.send_message({
                'type': 'error',
                'message': 'Invalid JSON format'
            })
        except Exception as e:
            print(f"[WebSocket] 處理訊息時發生錯誤: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message({
                'type': 'error',
                'message': f'Server error: {str(e)}'
            })
        
        print("=" * 50)
    
    # ==================== 播放控制方法 ====================
    
    async def init_playback(self, data):
        """初始化播放器"""
        print("[Playback] 初始化播放器...")
        
        self.filename = data.get('filename', 'show.pxld')
        self.slave_id = data.get('slave_id', -1)
        
        print(f"[Playback] filename: {self.filename}")
        print(f"[Playback] slave_id: {self.slave_id}")
        
        try:
            # 獲取解碼器
            from .pxld_v3_decoder_api import PXLDv3DecoderAPI
            filepath = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / self.filename
            
            print(f"[Playback] 文件路徑: {filepath}")
            print(f"[Playback] 文件是否存在: {filepath.exists()}")
            
            if not filepath.exists():
                raise FileNotFoundError(f"PXLD 文件不存在: {filepath}")
            
            self.decoder = PXLDv3DecoderAPI(str(filepath))
            
            if not self.decoder or not self.decoder.fh:
                raise ValueError("解碼器初始化失敗")
            
            # 設置播放參數
            self.fps = self.decoder.fh.fps
            self.total_frames = self.decoder.fh.total_frames
            
            print(f"[Playback] FPS: {self.fps}")
            print(f"[Playback] 總幀數: {self.total_frames}")
            
            response = {
                'type': 'playback_ready',
                'fps': self.fps,
                'total_frames': self.total_frames,
                'total_slaves': self.decoder.fh.total_slaves,
                'filename': self.filename
            }
            
            print(f"[Playback] 發送就緒訊息: {response}")
            await self.send_message(response)
            print("[Playback] 初始化成功")
            
        except Exception as e:
            print(f"[Playback] 初始化失敗: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'Failed to load PXLD file: {str(e)}'
            })
    
    async def start_playback(self, data):
        """開始播放"""
        print("[Playback] 開始播放...")
        
        if not self.decoder:
            print("[Playback] 錯誤: 播放器未初始化")
            await self.send_message({
                'type': 'playback_error',
                'message': 'Playback not initialized'
            })
            return
        
        # 停止現有播放任務
        if self.playback_task:
            print("[Playback] 取消現有播放任務")
            self.playback_task.cancel()
        
        self.playing = True
        start_frame = data.get('frame', 0)
        self.current_frame = start_frame
        
        print(f"[Playback] 從第 {start_frame} 幀開始播放")
        
        # 創建播放任務
        self.playback_task = asyncio.create_task(self.playback_loop())
        
        await self.send_message({
            'type': 'playback_started',
            'frame': self.current_frame,
            'fps': self.fps
        })
        print("[Playback] 播放已開始")
    
    async def playback_loop(self):
        """播放循環"""
        frame_time = 1.0 / self.fps
        print(f"[Playback] 播放循環開始，幀時間: {frame_time:.3f}s")
        
        try:
            frame_count = 0
            while self.playing and self.current_frame < self.total_frames:
                start_time = asyncio.get_event_loop().time()
                
                # 發送當前幀
                await self.send_frame_data(self.current_frame)
                
                # 更新幀號
                self.current_frame += 1
                if self.current_frame >= self.total_frames:
                    self.current_frame = 0
                
                frame_count += 1
                
                # 每 30 幀記錄一次
                if frame_count % 30 == 0:
                    print(f"[Playback] 已播放 {frame_count} 幀")
                
                # 計算等待時間
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_time = max(0, frame_time - elapsed)
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    # 如果處理時間超過了幀時間，跳過一些幀以保持同步
                    skip_frames = int(elapsed / frame_time)
                    if skip_frames > 0:
                        print(f"[Playback] 性能不足，跳過 {skip_frames} 幀")
                        self.current_frame += skip_frames
                        if self.current_frame >= self.total_frames:
                            self.current_frame %= self.total_frames
        
        except asyncio.CancelledError:
            print("[Playback] 播放任務被取消")
        except Exception as e:
            print(f"[Playback] 播放循環錯誤: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message({
                'type': 'playback_error',
                'message': f'Playback error: {str(e)}'
            })
    
    async def pause_playback(self):
        """暫停播放"""
        print("[Playback] 暫停播放")
        self.playing = False
        await self.send_message({
            'type': 'playback_paused',
            'frame': self.current_frame
        })
    
    async def stop_playback(self):
        """停止播放"""
        print("[Playback] 停止播放")
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
        
        print(f"[Playback] 跳轉到幀 {frame}")
        
        # 發送該幀的數據
        await self.send_frame_data(frame)
    
    async def get_single_frame(self, data):
        """獲取單個幀數據"""
        frame = data.get('frame', 0)
        slave_id = data.get('slave_id', self.slave_id)
        
        print(f"[Playback] 獲取單幀: frame={frame}, slave_id={slave_id}")
        
        await self.send_frame_data(frame, slave_id)
    
    async def send_frame_data(self, frame, slave_id=None):
        """發送幀數據"""
        if not self.decoder:
            print("[Playback] 錯誤: 解碼器未初始化")
            return
        
        if slave_id is None:
            slave_id = self.slave_id
        
        try:
            # 獲取幀數據
            print(f"[Playback] 獲取幀數據: frame={frame}, slave_id={slave_id}")
            rgbw_bytes = self.decoder.get_slave_rgbw_bytes(frame, slave_id)
            print(f"[Playback] RGBW 數據大小: {len(rgbw_bytes)} bytes")
            
            rgbw_base64 = base64.b64encode(rgbw_bytes).decode('ascii')
            
            # 發送消息
            response = {
                'type': 'frame_data',
                'frame': frame,
                'slave_id': slave_id,
                'rgbw_b64': rgbw_base64[:50] + '...',  # 只記錄前 50 個字符
                'timestamp': datetime.now().isoformat()
            }
            
            # 實際發送完整數據
            full_response = {
                'type': 'frame_data',
                'frame': frame,
                'slave_id': slave_id,
                'rgbw_b64': rgbw_base64,
                'timestamp': datetime.now().isoformat()
            }
            
            await self.send_message(full_response)
            # print(f"[Playback] 幀數據已發送")
            
        except Exception as e:
            print(f"[Playback] 獲取幀數據錯誤: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'Error getting frame {frame}: {str(e)}'
            })
    
    # ==================== 工具方法 ====================
    
    async def send_message(self, data):
        """發送 JSON 消息的包裝方法"""
        try:
            await self.send(text_data=json.dumps(data))
        except Exception as e:
            print(f"[WebSocket] 發送訊息錯誤: {e}")
            import traceback
            traceback.print_exc()
import json
import os
from datetime import datetime
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from .pxld_v3_decoder_api import PXLDv3DecoderAPI
import base64

class LightControlConsumer(AsyncWebsocketConsumer):
    """WebSocket 消費者，處理 LED 控制與播放"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decoder = None
        self.slave_id = -1  # 默認為總畫板模式
        self.filename = None
        self.playback_task = None
        self.is_playing = False
        self.current_frame = 0
    
    async def connect(self):
        """WebSocket 連接建立"""
        await self.accept()
        print(f"[WebSocket] 新連接建立: {self.scope['client']}")
        
        # 發送連接確認消息
        await self.send_message({
            'type': 'connection',
            'message': 'WebSocket 連接已建立',
            'timestamp': datetime.now().isoformat()
        })
    
    async def disconnect(self, close_code):
        """WebSocket 連接斷開"""
        print(f"[WebSocket] 連接斷開: code={close_code}")
        
        # 停止播放任務
        if self.playback_task:
            self.is_playing = False
            self.playback_task.cancel()
            print("[WebSocket] 播放任務已停止")
        
        # 關閉解碼器
        if self.decoder:
            self.decoder = None
            print("[WebSocket] 解碼器已釋放")
    
    async def receive(self, text_data):
        """處理 WebSocket 消息"""
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            
            print(f"[WebSocket] 收到消息類型: {msg_type}")
            
            if msg_type == 'playback_init':
                # 初始化播放器
                filename = data.get('filename', 'show.pxld')
                slave_id = data.get('slave_id', -1)  # 默認為總畫板模式
                
                await self.initialize_playback(filename, slave_id)
            
            elif msg_type == 'playback_play':
                # 開始播放
                frame = data.get('frame', 0)
                slave_id = data.get('slave_id', self.slave_id)
                
                await self.start_playback(frame, slave_id)
            
            elif msg_type == 'playback_pause':
                # 暫停播放
                await self.pause_playback()
            
            elif msg_type == 'playback_stop':
                # 停止播放
                await self.stop_playback()
            
            elif msg_type == 'playback_seek':
                # 跳轉到指定幀
                frame = data.get('frame', 0)
                slave_id = data.get('slave_id', self.slave_id)
                
                await self.seek_playback(frame, slave_id)
            
            elif msg_type == 'playback_get_frame':
                # 獲取特定幀
                frame = data.get('frame', 0)
                slave_id = data.get('slave_id', self.slave_id)
                
                await self.send_frame_data(frame, slave_id)
            
            elif msg_type == 'test_message':
                # 測試消息
                await self.handle_test_message(data)
            
            elif msg_type == 'ping':
                # 心跳檢測
                await self.send_message({
                    'type': 'pong',
                    'timestamp': datetime.now().isoformat()
                })
            
            else:
                print(f"[WebSocket] 未知消息類型: {msg_type}")
                await self.send_message({
                    'type': 'error',
                    'message': f'未知消息類型: {msg_type}'
                })
        
        except json.JSONDecodeError as e:
            print(f"[WebSocket] JSON 解析錯誤: {e}")
            await self.send_message({
                'type': 'error',
                'message': f'JSON 解析錯誤: {str(e)}'
            })
        
        except Exception as e:
            print(f"[WebSocket] 處理消息錯誤: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'error',
                'message': f'處理消息錯誤: {str(e)}'
            })
    
    async def initialize_playback(self, filename, slave_id):
        """初始化播放器"""
        try:
            # 設置參數
            self.slave_id = slave_id
            self.filename = filename
            
            # 構建文件路徑
            pxld_path = os.path.join(settings.MEDIA_ROOT, "netlight", "pxld", filename)
            
            if not os.path.exists(pxld_path):
                raise FileNotFoundError(f"PXLD 文件不存在: {pxld_path}")
            
            # 初始化解碼器
            self.decoder = PXLDv3DecoderAPI(pxld_path)
            
            # 獲取文件信息
            total_frames = self.decoder.fh.total_frames
            fps = self.decoder.fh.fps
            total_slaves = self.decoder.fh.total_slaves
            
            print(f"[Playback] 初始化成功: 文件={filename}, slave_id={slave_id}")
            print(f"[Playback] 總幀數={total_frames}, FPS={fps}, 總slave數={total_slaves}")
            
            # 發送準備就緒消息
            await self.send_message({
                'type': 'playback_ready',
                'filename': filename,
                'slave_id': slave_id,
                'total_frames': total_frames,
                'fps': fps,
                'total_slaves': total_slaves,
                'mode': 'all_slaves' if slave_id == -1 else 'single_slave',
                'timestamp': datetime.now().isoformat()
            })
        
        except Exception as e:
            print(f"[Playback] 初始化錯誤: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'初始化失敗: {str(e)}',
                'error_details': str(e),
                'timestamp': datetime.now().isoformat()
            })
    
    async def start_playback(self, start_frame, slave_id):
        """開始播放"""
        try:
            # 檢查解碼器
            if not self.decoder:
                raise ValueError("播放器未初始化")
            
            # 更新參數
            self.slave_id = slave_id
            self.current_frame = start_frame
            self.is_playing = True
            
            print(f"[Playback] 開始播放: frame={start_frame}, slave_id={slave_id}")
            
            # 發送播放開始消息
            await self.send_message({
                'type': 'playback_started',
                'frame': start_frame,
                'slave_id': slave_id,
                'timestamp': datetime.now().isoformat()
            })
            
            # 開始播放循環
            await self.playback_loop()
        
        except Exception as e:
            print(f"[Playback] 開始播放錯誤: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'開始播放失敗: {str(e)}',
                'timestamp': datetime.now().isoformat()
            })
    
    async def playback_loop(self):
        """播放循環"""
        try:
            fps = self.decoder.fh.fps
            total_frames = self.decoder.fh.total_frames
            
            print(f"[Playback] 播放循環開始: FPS={fps}, 總幀數={total_frames}")
            
            # 計算幀間隔 (毫秒)
            frame_interval = 1000 / fps
            
            # 開始循環發送幀數據
            while self.is_playing and self.current_frame < total_frames:
                start_time = datetime.now()
                
                # 發送當前幀數據
                await self.send_frame_data(self.current_frame, self.slave_id)
                
                # 計算下一幀
                self.current_frame += 1
                
                # 如果到達末尾，循環播放
                if self.current_frame >= total_frames:
                    self.current_frame = 0
                    print("[Playback] 到達末尾，循環播放")
                
                # 計算等待時間
                elapsed = (datetime.now() - start_time).total_seconds() * 1000
                wait_time = max(0, frame_interval - elapsed)
                
                # 等待下一幀
                if wait_time > 0:
                    import asyncio
                    await asyncio.sleep(wait_time / 1000)
            
            print("[Playback] 播放循環結束")
        
        except asyncio.CancelledError:
            print("[Playback] 播放循環被取消")
            raise
        
        except Exception as e:
            print(f"[Playback] 播放循環錯誤: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'播放循環錯誤: {str(e)}',
                'timestamp': datetime.now().isoformat()
            })
    
    async def pause_playback(self):
        """暫停播放"""
        self.is_playing = False
        print(f"[Playback] 播放暫停: current_frame={self.current_frame}")
        
        await self.send_message({
            'type': 'playback_paused',
            'frame': self.current_frame,
            'timestamp': datetime.now().isoformat()
        })
    
    async def stop_playback(self):
        """停止播放"""
        self.is_playing = False
        self.current_frame = 0
        print("[Playback] 播放停止")
        
        await self.send_message({
            'type': 'playback_stopped',
            'timestamp': datetime.now().isoformat()
        })
    
    async def seek_playback(self, frame, slave_id):
        """跳轉到指定幀"""
        try:
            # 檢查幀範圍
            total_frames = self.decoder.fh.total_frames
            if frame < 0 or frame >= total_frames:
                raise ValueError(f"幀 {frame} 超出範圍 (0-{total_frames-1})")
            
            # 更新當前幀
            self.current_frame = frame
            self.slave_id = slave_id
            
            print(f"[Playback] 跳轉到幀: frame={frame}, slave_id={slave_id}")
            
            # 發送跳轉確認
            await self.send_message({
                'type': 'playback_seeked',
                'frame': frame,
                'slave_id': slave_id,
                'timestamp': datetime.now().isoformat()
            })
            
            # 發送該幀數據
            await self.send_frame_data(frame, slave_id)
        
        except Exception as e:
            print(f"[Playback] 跳轉錯誤: {e}")
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'跳轉失敗: {str(e)}',
                'timestamp': datetime.now().isoformat()
            })
    
    async def send_frame_data(self, frame, slave_id=None):
        """發送幀數據"""
        if not self.decoder:
            print("[Playback] 錯誤: 解碼器未初始化")
            return
        
        if slave_id is None:
            slave_id = self.slave_id
        
        try:
            # 判斷是總畫板模式還是單個 slave 模式
            if slave_id == -1:
                # 總畫板模式：發送所有 slave 的數據
                print(f"[Playback] 獲取所有 slave 的幀數據: frame={frame}")
                
                # 使用新的方法獲取所有 slave 數據
                all_rgbw_b64 = self.decoder.get_all_slaves_rgbw_b64(frame)
                
                slaves_data = []
                for sid, rgbw_b64 in sorted(all_rgbw_b64.items()):
                    # 獲取該 slave 的 pixel_count
                    frame_data = self.decoder._read_frame_tables(frame)
                    pixel_count = 0
                    for slave_meta in frame_data["slaves"]:
                        if slave_meta.slave_id == sid:
                            pixel_count = slave_meta.pixel_count
                            break
                    
                    slaves_data.append({
                        'slave_id': sid,
                        'rgbw_b64': rgbw_b64,
                        'pixel_count': pixel_count
                    })
                
                # 發送所有 slave 的數據
                response = {
                    'type': 'frame_data_all',  # 新類型
                    'frame': frame,
                    'slaves': slaves_data,
                    'timestamp': datetime.now().isoformat(),
                    'total_slaves': len(slaves_data)
                }
                await self.send_message(response)
                print(f"[Playback] 所有 slave 幀數據已發送: {len(slaves_data)} 個 slave")
            
            else:
                # 單個 slave 模式
                print(f"[Playback] 獲取幀數據: frame={frame}, slave_id={slave_id}")
                rgbw_bytes = self.decoder.get_slave_rgbw_bytes(frame, slave_id)
                rgbw_base64 = base64.b64encode(rgbw_bytes).decode('ascii')
                
                # 獲取 pixel_count
                frame_data = self.decoder._read_frame_tables(frame)
                pixel_count = 0
                for slave_meta in frame_data["slaves"]:
                    if slave_meta.slave_id == slave_id:
                        pixel_count = slave_meta.pixel_count
                        break
                
                response = {
                    'type': 'frame_data',
                    'frame': frame,
                    'slave_id': slave_id,
                    'rgbw_b64': rgbw_base64,
                    'pixel_count': pixel_count,
                    'timestamp': datetime.now().isoformat()
                }
                await self.send_message(response)
                print(f"[Playback] 幀數據已發送: slave_id={slave_id}, pixel_count={pixel_count}")
        
        except Exception as e:
            print(f"[Playback] 獲取幀數據錯誤: {e}")
            import traceback
            traceback.print_exc()
            
            await self.send_message({
                'type': 'playback_error',
                'message': f'獲取幀 {frame} 數據錯誤: {str(e)}',
                'frame': frame,
                'slave_id': slave_id,
                'timestamp': datetime.now().isoformat()
            })
    
    async def handle_test_message(self, data):
        """處理測試消息"""
        message = data.get('message', 'Test message')
        print(f"[WebSocket] 測試消息: {message}")
        
        await self.send_message({
            'type': 'test_response',
            'message': f'收到測試消息: {message}',
            'original': message,
            'timestamp': datetime.now().isoformat()
        })
    
    async def send_message(self, data):
        """發送 WebSocket 消息"""
        try:
            await self.send(text_data=json.dumps(data))
        except Exception as e:
            print(f"[WebSocket] 發送消息錯誤: {e}")
            import traceback
            traceback.print_exc()



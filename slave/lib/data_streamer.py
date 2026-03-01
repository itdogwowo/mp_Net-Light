import socket
import time
import select
from lib.sys_bus import bus

class DataStreamer:
    """
    極限性能數據接收器 (Turbo Channel)
    監聽 Raw TCP 端口 (默認 8889) 並直接寫入 AtomicStreamHub
    支持幀對齊 (Frame Alignment) 以防止畫面撕裂
    """
    def __init__(self, port=8889):
        self.port = port
        self.sock = None
        self.client = None
        self.addr = None
        self.hub = None
        self.active = False
        
        # 幀對齊狀態
        self.current_view = None
        self.view_offset = 0
        
    def start(self):
        """啟動監聽"""
        try:
            self.hub = bus.get_service("pixel_stream")
            if not self.hub:
                print("❌ DataStreamer: Pixel Hub not found")
                return

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('0.0.0.0', self.port))
            self.sock.listen(1)
            self.sock.setblocking(False) # 非阻塞監聽
            self.active = True
            print(f"🚀 [Turbo] Listening on Raw TCP port {self.port}")
        except Exception as e:
            print(f"❌ [Turbo] Start Failed: {e}")

    def poll(self):
        """
        在 Core0 循環中調用
        """
        if not self.active: return False

        # 1. 檢查新連接
        if not self.client:
            try:
                conn, addr = self.sock.accept()
                print(f"🔌 [Turbo] Client Connected: {addr}")
                conn.setblocking(False)
                try:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except:
                    pass
                self.client = conn
                self.addr = addr
                
                # 重置狀態
                self.current_view = None
                self.view_offset = 0
                
                # 自動切換模式
                bus.shared["is_streaming"] = True
                bus.shared["play_mode"] = 2
            except OSError:
                pass
            return False

        # 2. 數據接收 (狀態機)
        try:
            # 如果還沒有拿到 Hub 的 Buffer，嘗試獲取
            if self.current_view is None:
                self.current_view = self.hub.get_write_view()
                self.view_offset = 0
                
                if self.current_view is None:
                    return False # Hub 滿了，稍後再試

            # 嘗試讀取剩餘需要的數據量
            # view[start:end] 在 MicroPython 中通常不會複製內存，而是返回新的 slice view
            # 但為了保險和性能，我們直接用 offset 計算
            # 注意: readinto 不支持 offset 參數，必須用 slice
            # client.readinto(view[offset:])
            
            needed = len(self.current_view) - self.view_offset
            target_slice = self.current_view[self.view_offset:]
            
            try:
                n = self.client.readinto(target_slice)
                
                if n is None: return False # EAGAIN
                if n == 0:
                    self._close_client()
                    return False
                
                self.view_offset += n
                
                # 檢查是否填滿
                if self.view_offset == len(self.current_view):
                    self.hub.commit() # 提交完整幀
                    self.current_view = None # 準備下一幀
                    self.view_offset = 0
                    return True # 繼續處理 (可能還有數據)
                    
            except OSError as e:
                if e.args[0] == 11: return False # EAGAIN
                raise e

        except Exception as e:
            print(f"❌ [Turbo] Stream Error: {e}")
            self._close_client()
            return False

    def _close_client(self):
        if self.client:
            try: self.client.close()
            except: pass
        print(f"🔌 [Turbo] Client Disconnected")
        self.client = None
        self.addr = None
        self.current_view = None
        self.view_offset = 0

    def stop(self):
        self.active = False
        self._close_client()
        if self.sock:
            try: self.sock.close()
            except: pass
        self.sock = None

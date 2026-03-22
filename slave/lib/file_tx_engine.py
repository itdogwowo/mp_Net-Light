import os
import ubinascii
from lib.sys_bus import bus

class FileTxEngine:
    """
    Core 1 端文件處理引擎
    負責從 FileRxHub 消費數據，寫入存儲並校驗
    """
    def __init__(self, hub):
        self.hub = hub
        self.fp = None
        self.current_fid = None
        self.written_bytes = 0
        self.last_state = None
        
    def _close_file(self):
        if self.fp:
            try:
                self.fp.flush()
                # 某些平台支持 sync
                if hasattr(os, "sync"): os.sync()
                self.fp.close()
            except: pass
            self.fp = None

    def process(self, session):
        """
        處理一次文件任務 (非阻塞)
        session: 來自 bus.shared["file_session"] 的狀態字典
        """
        state = session.get("state")
        fid = session.get("file_id")
        
        if state == "error" or state == "done":
            return
        
        # 1. 初始化新文件
        if self.current_fid != fid:
            self._close_file()
            self.current_fid = fid
            self.written_bytes = 0
            
            # 如果需要保存 (save_mode=1)，打開文件
            if session.get("save_mode") == 1:
                try:
                    path = session.get("path")
                    # 確保目錄存在 (可選)
                    # self._ensure_dir(path)
                    self.fp = open(path, "wb")
                    print(f"💾 [Core1] Saving to: {path}")
                except Exception as e:
                    print(f"❌ [Core1] Open Error: {e}")
                    session["state"] = "error"
                    return

        # 2. 消費數據 (從 Hub 讀取)
        # Hub 可能處於兩種模式:
        # A. Full RAM: 只有一個大 buffer，Core 0 寫完後 commit
        # B. Double Buffer: 兩個 buffer 交替
        
        # 檢查 Hub 是否有準備好的數據 (dirty)
        if self.hub.dirty:
            view = self.hub.get_read_view()
            if view:
                # 有新數據！
                try:
                    # 寫入文件 (如果需要)
                    if self.fp:
                        n = self.fp.write(view)
                        self.written_bytes += n
                    
                    # SHA256 已經在 Core 0 寫入時流式計算了，這裡不需要再算
                    # 除非我們不信任 Core 0 的 RAM 數據
                    
                except Exception as e:
                    print(f"❌ [Core1] Write Error: {e}")
                    session["state"] = "error"
                finally:
                    # 釋放 Hub 緩衝區，讓 Core 0 繼續填
                    # 這裡調用 read_into 其實有點語義不清，應該用 finish_read 或類似
                    # 不過 Hub 的設計是 get_read_view 後必須要 read_into 或釋放
                    # 為了簡單，我們這裡只要不 hold 住 view 就行
                    # AtomicStreamHub 需要顯示的信號來釋放
                    # 我們這裡用一個 trick: get_read_view 會鎖定，我們需要一個方法解鎖
                    # Hub 的邏輯是 get_read_view -> read_into -> 釋放
                    # 或者 get_read_view (下次調用自動釋放上次)
                    # 這裡我們不需要拷貝數據，只是消費
                    # 暫時不做額外操作，下次循環 get_read_view 會自動釋放上一個
                    pass
                
        # 3. 檢查結束狀態
        # 只有當 Core 0 說結束了 (finishing)，且 Hub 裡沒有數據了 (dirty=False)，才算真正結束
        if state == "finishing":
            if not self.hub.dirty:
                self._finish_session(session)

    def _finish_session(self, session):
        """結束會話，進行最終校驗"""
        print(f"🏁 [Core1] Finishing File: {self.current_fid}")
        self._close_file()
        
        # 獲取最終 SHA256
        digest = self.hub.get_digest()
        expected = session.get("sha256")
        
        status = 0 # OK
        
        if digest and expected:
            if digest != expected:
                print(f"❌ SHA256 Mismatch!")
                print(f"   Got: {ubinascii.hexlify(digest)}")
                print(f"   Exp: {ubinascii.hexlify(expected)}")
                status = 2 # Error
            else:
                print("✅ SHA256 Verified")
        
        # 清理 Hub 內存 (恢復小緩衝)
        # 注意: 這裡調用會導致 Hub 釋放內存，Core 0 那邊如果還在訪問會崩
        # 所以確保 Core 0 已經完全退出
        self.hub.close_session()
        
        # 更新 Session 狀態通知 Core 0 / Monitor
        session["state"] = "done"
        session["status"] = status
        
        # 重置本地狀態
        self.current_fid = None

import hashlib
import ubinascii
import os



import gc
try:
    import machine
except:
    pass

class FileRx:
    """
    高性能文件接收組件 - 智能緩衝管理與策略執行
    """
    MODE_WRITE = 0   # 截斷寫入 (wb)
    MODE_UPDATE = 1  # 原地更新 (r+b)
    MODE_RAM = 2     # 純 RAM 模式 (不寫 Flash)

    def __init__(self, buf_size=4096):
        self.buf_size = buf_size
        self.hub = None 
        self.reset()
        self.last_sha_hex = ""
        self._sha_calc = None # 實時計算的 SHA256 對象

    def sha256_digest_stream_from_file(self, path, bufsize=None):
        """
        串流計算文件 SHA256，避免將大文件一次性載入記憶體導致 OOM。
        使用 memoryview 優化字節切片效能。
        """
        if bufsize is None: bufsize = self.buf_size
        h = hashlib.sha256()
        buf = bytearray(bufsize)
        mv = memoryview(buf) # 預先創建 memoryview
        
        with open(str(path), "rb") as f:
            while True:
                n = f.readinto(buf)
                if n == 0:
                    break
                # 使用 memoryview 避免產生臨時 bytes 對象
                h.update(mv[:n])
        return h.digest()

    def reset(self):
        """重置接收狀態"""
        self.active = False
        self.file_id = 0
        self.total = 0
        self.path = None
        self.fp = None
        self.written = 0
        self.sha_expect = None
        self.last_error = None
        self.mode = self.MODE_WRITE
        self._sha_calc = None
        
        # 釋放舊 Hub (如果是由 FileRx 管理的)
        if self.hub:
            self.hub.flush()
            self.hub = None

    def analyze_file(self, path, expected_size):
        """
        分析目標文件狀態，決定寫入策略
        返回: (exists, size, sha256_bytes)
        """
        try:
            s = os.stat(path)
            size = s[6]
            # 只有當大小一致時才計算 SHA (為了速度)
            if size == expected_size:
                # 使用大緩衝 (64KB) 快速掃描
                sha = self.sha256_digest_stream_from_file(path, bufsize=65536)
                return True, size, sha
            return True, size, None
        except:
            return False, 0, None

    def _close(self):
        """安全關閉文件句柄，並強制刷入磁盤"""
        if self.fp:
            try:
                self.fp.flush()
                # 某些 MicroPython 端口支援 os.sync()
                if hasattr(os, 'sync'):
                    os.sync()
                self.fp.close()
            except:
                pass
        self.fp = None

    def begin(self, args: dict) -> object:
        """
        FILE_BEGIN (0x2001)
        返回: 創建的 AtomicStreamHub 對象 (如果成功)，否則 None
        """
        self._close()
        self.reset()
        
        self.file_id = int(args.get("file_id", 0))
        self.total = int(args.get("total_size", 0))
        self.path = args.get("path")
        self.sha_expect = args.get("sha256") # Master 傳來的期望 SHA (bytes)
        req_mode = int(args.get("mode", 0))  # 0:Auto, 1:Reliable, 2:Stream
        
        if not self.path:
            self.last_error = "MISSING_PATH"
            return None

        # 1. 決定模式
        if self.path.startswith("ram://"):
            self.mode = self.MODE_RAM
            print(f"💾 [FileRx] Mode: RAM ONLY")
        elif req_mode == 1:
            # 強制 Reliable (Truncate)
            self.mode = self.MODE_WRITE
            print(f"💾 [FileRx] Mode: WRITE (Reliable/Truncate)")
        elif req_mode == 2:
            # 強制 Stream (Update)
            self.mode = self.MODE_UPDATE
            # 如果文件不存在，自動降級為 WRITE
            try:
                os.stat(self.path)
                print(f"💾 [FileRx] Mode: UPDATE (Stream/Overwrite)")
            except:
                self.mode = self.MODE_WRITE
                print(f"💾 [FileRx] Mode: WRITE (Stream/New)")
        else:
            # Auto (舊邏輯)
            exists, size, curr_sha = self.analyze_file(self.path, self.total)
            if exists and size == self.total:
                self.mode = self.MODE_UPDATE
                print(f"💾 [FileRx] Mode: UPDATE (Auto/Overwrite)")
            else:
                self.mode = self.MODE_WRITE
                print(f"💾 [FileRx] Mode: WRITE (Auto/Truncate)")
                
        # 2. 準備 SHA 計算器
        self._sha_calc = hashlib.sha256()

        # 3. 打開文件
        try:
            if self.mode == self.MODE_UPDATE:
                self.fp = open(self.path, "r+b")
            elif self.mode == self.MODE_WRITE:
                self.fp = open(self.path, "wb")
            # RAM 模式不需要文件句柄
        except Exception as e:
            self.last_error = f"OPEN_FAIL: {e}"
            return None

        # 4. 動態申請 Hub (3/5 Free RAM)
        # 獲取可用 RAM
        gc.collect()
        free_ram = gc.mem_free()
        
        # 計算目標 Hub 大小 (3/5)
        # 為了對齊，我們先算出有多少個完整的 64KB block
        target_mem = int(free_ram * 0.6)
        slot_size = 65536
        
        # 直接整除，捨棄餘數 (避免碎片)
        num_slots = target_mem // slot_size
        
        # 確保至少有 3 個 (Triple Buffering)
        if num_slots < 3: num_slots = 3
        
        # 限制最大 Slot 數量 (256 = 16MB)
        if num_slots > 256: num_slots = 256
        
        real_alloc = num_slots * slot_size
        print(f"🧠 [FileRx] Allocating Hub: {num_slots} slots x 64KB (Total: {real_alloc//1024} KB)")
        
        try:
            # 這裡需要引入 AtomicStreamHub，避免循環引用，我們假設外部傳入或在此 import
            from lib.buffer_hub import AtomicStreamHub
            self.hub = AtomicStreamHub(slot_size, num_slots, name=f"frx_{self.file_id}")
        except Exception as e:
            self.last_error = f"HUB_ALLOC_FAIL: {e}"
            self._close()
            return None
            
        self.active = True
        return self.hub

    def process_hub_data(self):
        """
        [Core 1 消費者] 從 Hub 取數據 -> 校驗 -> 寫入/丟棄
        """
        if not self.active or not self.hub:
            return

        view = self.hub.get_read_view()
        if view:
            try:
                # 1. 實時校驗 (計算 SHA256)
                if self._sha_calc:
                    self._sha_calc.update(view)

                # 2. 寫入 (如果需要)
                if self.mode != self.MODE_RAM and self.fp:
                    self.fp.write(view)
                
                # 3. 進度更新
                self.written += len(view)
                
            except Exception as e:
                self.last_error = f"CONSUME_FAIL: {e}"
                self.active = False
            
            # 隱式釋放 Slot
            pass

    def get_final_sha(self):
        """獲取計算出的最終 SHA256 (bytes)"""
        if self._sha_calc:
            return self._sha_calc.digest()
        return None

    def chunk(self, args: dict) -> bool:
        """
        FILE_CHUNK (0x2002) 處理邏輯
        """
        if not self.active:
            self.last_error = "NO_ACTIVE_SESSION"
            return False
        
        # 移除 file_id 檢查
        # if int(args.get("file_id", 0)) != self.file_id:
        #    return False

        data = args.get("data", b"")
        
        # 分支邏輯：有 Hub 則推入 Hub，否則直接寫入
        if self.hub:
            # 嘗試寫入 Hub (非阻塞)
            # 如果 Hub 滿了，這裡會返回 False (Backpressure)
            if self.hub.write_from(data):
                return True
            else:
                return False
        else:
            # 傳統同步模式
            try:
                off = int(args.get("offset", 0))
                # 只有當 offset 不在當前磁頭位置時才執行 seek
                if self.fp and off != self.written:
                    self.fp.seek(off)
                    self.written = off # 校正
                
                if self.fp:
                    self.fp.write(data)
                    self.written += len(data)
                return True
            except Exception as e:
                self.last_error = f"WRITE_FAIL: {e}"
                self.active = False
                return False

    def end(self, args: dict) -> bool:
        """
        FILE_END (0x2003) 處理邏輯
        """
        if not self.active:
            return False
            
        # 1. 確保所有 Hub 數據已消費
        # 這裡我們做一個簡單的 flush loop
        if self.hub:
            # 嘗試最多 100 次循環，確保數據寫入
            for _ in range(100):
                if not self.hub.dirty: break
                self.process_hub_data()

        self._close()
        
        # 2. 獲取計算出的 SHA
        got_digest = self.get_final_sha()
        
        # 如果沒有實時計算 (舊模式)，則讀文件計算
        if not got_digest and self.path and not self.ram_only:
             try:
                 got_digest = self.sha256_digest_stream_from_file(self.path)
             except:
                 pass

        if not got_digest:
             self.last_error = "NO_DIGEST_CALC"
             self.active = False
             return False

        self.last_sha_hex = ubinascii.hexlify(got_digest).decode()
        exp_hex = ubinascii.hexlify(self.sha_expect).decode() if self.sha_expect else ""
        
        # 3. 比對
        if got_digest == self.sha_expect:
            self.active = False
            return True
        else:
            self.last_error = f"SHA_MISMATCH got {self.last_sha_hex} exp {exp_hex}"
            self.active = False
            return False
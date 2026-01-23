import hashlib
import ubinascii
import os

def sha256_digest_stream_from_file(path, bufsize=2048):
    """
    串流計算文件 SHA256，避免將大文件一次性載入記憶體導致 OOM。
    使用 memoryview 優化字節切片效能。
    """
    h = hashlib.sha256()
    buf = bytearray(bufsize)
    with open(str(path), "rb") as f:
        while True:
            n = f.readinto(buf)
            if n == 0:
                break
            # 使用 memoryview 避免產生臨時 bytes 對象
            h.update(memoryview(buf)[:n])
    return h.digest()

class FileRx:
    """
    高性能文件接收組件 - 支援分片寫入與 SHA256 流式校驗
    """
    def __init__(self):
        self.reset()
        self.last_sha_hex = "" # 儲存最後一次成功或失敗的哈希計算結果

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

    def begin(self, args: dict) -> bool:
        """
        FILE_BEGIN (0x2001) 處理邏輯
        """
        self._close()
        self.reset()
        
        self.file_id = int(args.get("file_id", 0))
        self.total = int(args.get("total_size", 0))
        self.path = args.get("path")
        self.sha_expect = args.get("sha256")
        
        if not self.path or not self.sha_expect:
            self.last_error = "MISSING_PATH_OR_SHA"
            return False

        try:
            # 以 'wb' 模式開啟會自動清空舊文件
            # 對於 ESP32-P4，直接順序寫入比頻繁 seek 預分配更快
            self.fp = open(self.path, "wb")
            self.active = True
            return True
        except Exception as e:
            self.last_error = f"OPEN_FAIL: {e}"
            return False

    def chunk(self, args: dict) -> bool:
        """
        FILE_CHUNK (0x2002) 處理邏輯
        支持斷點續傳地址定位，但推薦順序發送以獲得最高效能。
        """
        if not self.active or not self.fp:
            self.last_error = "NO_ACTIVE_SESSION"
            return False
        
        # 檢查 file_id 是否匹配當前任務
        if int(args.get("file_id", 0)) != self.file_id:
            return False

        off = int(args.get("offset", 0))
        data = args.get("data", b"")
        
        try:
            # 只有當 offset 不在當前磁頭位置時才執行 seek
            if off != self.written:
                self.fp.seek(off)
            
            self.fp.write(data)
            self.written = off + len(data)
            return True
        except Exception as e:
            self.last_error = f"WRITE_FAIL: {e}"
            self.active = False # 發生物理錯誤時解除激活
            return False

    def end(self, args: dict) -> bool:
        """
        FILE_END (0x2003) 處理邏輯
        執行最終的哈希驗證並關閉任務。
        """
        if not self.active:
            return False
            
        # 1. 先關閉文件，確保所有數據已從緩存刷入 Flash
        self._close()
        
        try:
            # 2. 計算實際寫入文件的哈希值
            got_digest = sha256_digest_stream_from_file(self.path)
            self.last_sha_hex = ubinascii.hexlify(got_digest).decode()
            
            # 3. 雙向對應
            if got_digest == self.sha_expect:
                self.active = False
                return True
            else:
                exp_hex = ubinascii.hexlify(self.sha_expect).decode()
                self.last_error = f"SHA_MISMATCH got {self.last_sha_hex}"
                self.active = False
                return False
        except Exception as e:
            self.last_error = f"VERIFY_ERR: {e}"
            self.active = False
            return False
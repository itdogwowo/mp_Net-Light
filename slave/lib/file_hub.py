import gc
import micropython
import hashlib
from lib.buffer_hub import AtomicStreamHub

class FileRxHub(AtomicStreamHub):
    """
    專為文件傳輸優化的 Hub
    支持動態內存分配、SHA256 流式計算、文件元數據管理
    """
    def __init__(self, size=4096, num_buffers=2):
        super().__init__(size, num_buffers)
        self.active_file = None
        self.sha256_ctx = None
        self.total_received = 0
        self.is_allocated = False

    def reallocate(self, size, num_buffers=2):
        """
        動態調整緩衝區大小 (針對大文件傳輸)
        會先釋放舊內存，再分配新內存
        """
        # 1. 釋放舊資源
        self._bufs = None
        self._views = None
        self._status = None
        gc.collect()

        # 2. 分配新資源
        print(f"📦 [FileHub] Reallocating: {size} bytes x {num_buffers}")
        try:
            self._bufs = [bytearray(size) for _ in range(num_buffers)]
            self._views = [memoryview(b) for b in self._bufs]
            self._status = [AtomicStreamHub.IDLE] * num_buffers
            self.size = size
            self.num_buffers = num_buffers
            self._w_ptr = 0
            self._r_ptr = 0
            self._last_read_idx = None
            self.is_allocated = True
            print(f"✅ [FileHub] Reallocation Success: {gc.mem_free()//1024} KB Free")
            return True
        except MemoryError:
            print("❌ [FileHub] Reallocation Failed: Out of Memory")
            self.is_allocated = False
            return False

    def start_session(self, file_info):
        """開始一個新的文件傳輸會話"""
        self.active_file = file_info
        self.sha256_ctx = hashlib.sha256()
        self.total_received = 0
        self.flush() # 重置指針
        
        # 預計算分塊需求
        chunk_size = file_info.get("chunk_size", 4096)
        
        # 智能內存分配策略
        # 1. 如果文件小於剩餘 RAM 的 2/3，嘗試全量分配 (單緩衝)
        # 2. 否則，分配 2/3 RAM 作為雙緩衝
        free_ram = gc.mem_free()
        file_size = file_info["total_size"]
        
        target_buf_size = 4096
        target_buf_num = 2
        
        if file_size < (free_ram * 0.6):
            # 情況 A: 全量緩存 (極速模式)
            target_buf_size = file_size
            target_buf_num = 1
            print("🚀 [FileHub] Mode: Full RAM Cache")
        else:
            # 情況 B: 雙緩衝流式 (大文件模式)
            # 使用剩餘 RAM 的 60% 作為總緩衝池
            pool_size = int(free_ram * 0.6)
            target_buf_size = pool_size // 2
            target_buf_num = 2
            print("🔄 [FileHub] Mode: Streaming Double Buffer")
            
        # 執行分配
        return self.reallocate(target_buf_size, target_buf_num)

    def update_sha256(self, data):
        """更新當前文件的 SHA256"""
        if self.sha256_ctx:
            self.sha256_ctx.update(data)

    def get_digest(self):
        """獲取最終 SHA256"""
        if self.sha256_ctx:
            return self.sha256_ctx.digest()
        return None

    def close_session(self):
        self.active_file = None
        self.sha256_ctx = None
        # 傳輸結束後，釋放佔用的大內存，恢復到最小狀態
        self.reallocate(4096, 2)
    
    @micropython.native
    def write_from(self, source):
        """
        重寫 write_from 以支援自動指針偏移 (針對 Full RAM Mode)
        """
        if self.num_buffers == 1:
            # Full RAM Mode: 像文件一樣追加寫入
            ptr = self._w_ptr # 此時 ptr 用作 byte offset
            l = len(source)
            if ptr + l > self.size:
                return False # 溢出
            
            # 直接寫入對應位置
            self._views[0][ptr : ptr+l] = source
            self._w_ptr += l
            
            # 更新狀態為 READY (但這會導致 dirty 變為 True)
            # 為了避免過早 dirty，我們可以只在 commit 時標記
            # 但為了兼容性，我們先保持現狀
            self._status[0] = AtomicStreamHub.READY
            return True
        else:
            # 雙緩衝模式: 調用父類邏輯
            return super().write_from(source)

    @micropython.native
    def commit(self):
        """
        提交寫入 (標記數據已準備好)
        """
        if self.num_buffers == 1:
            # Full RAM Mode: 標記整個緩衝區為 READY
            self._status[0] = AtomicStreamHub.READY
            # r_ptr 重置為 0，以便消費者從頭讀取
            self._r_ptr = 0 
        else:
            super().commit()

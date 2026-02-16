# lib/buffer_hub.py
import gc
from lib.memory_manager import MemoryManager

class AtomicStreamHub:
    """
    AtomicStreamHub - 高效能無鎖多重緩衝管理器 (Ring Buffer)
    ═══════════════════════════════════════════════════════
    設計核心:
    1. 簡單易用: write_from / read_into 傻瓜式操作。
    2. 動態大內存: 使用 MemoryManager 從 PSRAM 分配。
    3. 環形隊列: 平滑網絡抖動。
    """
    
    # 槽位狀態
    IDLE = 0   # 空閒
    READY = 1  # 就緒

    def __init__(self, size, num_buffers=3):
        """
        :param size: 每個緩衝區的大小 (bytes)
        :param num_buffers: 緩衝區數量 (推薦 3)
        """
        self.size = size
        self.num_buffers = num_buffers
        self.mm = MemoryManager.get()
        
        # ── 預分配物理緩衝 ──
        self._bufs = []
        self._views = []
        for _ in range(num_buffers):
            buf = self.mm.rent_buffer(size, hard_limit=size, align=4)
            self._bufs.append(buf)
            self._views.append(memoryview(buf))
        
        # ── 狀態控制 ──
        self._status = [self.IDLE] * num_buffers
        self._w_ptr = 0  # 寫入指標
        self._r_ptr = 0  # 讀取指標
        
        # 兼容性標誌
        self.dirty = False 

        print(f"🚀 [BufferHub] Ready: {num_buffers}x {size//1024}KB")

    # ══════════════════════════════════════════════════════
    #  [用戶友善接口] User-Friendly API
    # ══════════════════════════════════════════════════════

    def write_from(self, source):
        """
        [生產者] 將數據寫入 HUB
        :param source: 來源數據 (bytes/bytearray/memoryview)
        :return: bool (True: 成功, False: 緩衝區滿)
        """
        ptr = self._w_ptr
        
        if self._status[ptr] != self.IDLE:
            return False
            
        try:
            # 自動處理長度差異
            l = len(source)
            if l == self.size:
                self._views[ptr][:] = source
            elif l < self.size:
                self._views[ptr][:l] = source
            else:
                self._views[ptr][:] = source[:self.size]
        except Exception:
            return False
            
        self._status[ptr] = self.READY
        self._w_ptr = (ptr + 1) % self.num_buffers
        self.dirty = True
        return True

    def read_into(self, target):
        """
        [消費者] 將數據讀出到目標緩衝區
        :param target: 目標緩衝區 (必須預分配好)
        :return: bool (True: 成功, False: 無數據)
        """
        ptr = self._r_ptr
        
        if self._status[ptr] != self.READY:
            return False
            
        target[:self.size] = self._views[ptr]
        
        self._status[ptr] = self.IDLE
        self._r_ptr = (ptr + 1) % self.num_buffers
        
        self.dirty = (self._status[self._r_ptr] == self.READY)
        return True

    def flush(self):
        """快速清空所有狀態"""
        for i in range(self.num_buffers):
            self._status[i] = self.IDLE
        self._w_ptr = 0
        self._r_ptr = 0
        self.dirty = False

    # ══════════════════════════════════════════════════════
    #  [零拷貝進階接口] Zero-Copy API (兼容舊代碼)
    # ══════════════════════════════════════════════════════

    def get_write_view(self):
        """獲取當前可寫視圖 (需配合 commit 使用)"""
        ptr = self._w_ptr
        if self._status[ptr] != self.IDLE: return None
        return self._views[ptr]

    def commit(self):
        """提交當前寫入"""
        ptr = self._w_ptr
        self._status[ptr] = self.READY
        self._w_ptr = (ptr + 1) % self.num_buffers
        self.dirty = True

    def get_read_view(self):
        """獲取當前可讀視圖 (需自行決定何時釋放，此處為了兼容暫不自動釋放)"""
        ptr = self._r_ptr
        if self._status[ptr] != self.READY: return None
        # 注意：舊代碼在 get_read_view 後會假設數據一直有效直到下一次調用
        # 但在 RingBuffer 中，我們需要明確的釋放信號。
        # 為了兼容，這裡我們不移動指針，依賴外部調用 release (如果有的話) 
        # 或者我們假設每次 get_read_view 後就自動消費了？
        # 為了安全，這裡返回視圖，但要求用戶調用 release() 來推進指針
        return self._views[ptr]
        
    def release(self):
        """釋放當前讀取幀 (推進讀取指針)"""
        ptr = self._r_ptr
        self._status[ptr] = self.IDLE
        self._r_ptr = (ptr + 1) % self.num_buffers
        self.dirty = (self._status[self._r_ptr] == self.READY)

    def force_get_view(self):
        """強制獲取上一個已知數據 (用於靜態保持)"""
        # 回退一個位置 (注意負數處理)
        last_ptr = (self._r_ptr - 1 + self.num_buffers) % self.num_buffers
        return self._views[last_ptr]

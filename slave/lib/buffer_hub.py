# lib/buffer_hub.py
"""
AtomicStreamHub - 高效能無鎖三重緩衝管理器
═══════════════════════════════════════════════════════
設計核心:
1. 零 GC 壓力: 運行期間無對象創建。
2. 固定內存: 預分配所有 Buffer 與 View。
3. O(1) 指標操作: 嚴格環形順序，不依賴無限增長時間戳。
4. 數據隔離: 生產者與消費者完全解耦。
"""

class AtomicStreamHub:
    # 槽位狀態 (使用小整數，MicroPython 內部處理極快)
    IDLE = 0
    READY = 1

    def __init__(self, size, num_buffers=3):
        """
        :param size: 每個緩衝區的大小 (bytes)
        :param num_buffers: 緩衝區數量 (推薦 3)
        """
        # ── 預分配物理緩衝 ──
        self._bufs = [bytearray(size) for _ in range(num_buffers)]
        # ── 預分配視圖 (核心優化：避免運行時創建 view) ──
        self._views = [memoryview(b) for b in self._bufs]
        
        # ── 狀態控制 ──
        self._status = [self.IDLE] * num_buffers
        self._w_ptr = 0  # 寫入指標
        self._r_ptr = 0  # 讀取指標
        
        self.size = size
        self.num_buffers = num_buffers
        
        # 預先格式化診斷信息，避免運行時組裝字串
        print("🚀 [BufferHub] Ready: {} KB total".format((size * num_buffers) // 1024))

    def write_from(self, source):
        """
        將數據寫入 HUB
        ───────────────────────────────────────────────
        :param source: 來源數據 (bytes/bytearray/memoryview)
        :return: bool (True: 寫入成功, False: 緩衝區已滿)
        """
        ptr = self._w_ptr
        
        # 檢查當前指標指向的槽位是否可寫入
        if self._status[ptr] != self.IDLE:
            return False
        
        # 執行高效內存拷貝 (底層 C 實現)
        self._views[ptr][:] = source
        
        # 更新狀態與指標
        self._status[ptr] = self.READY
        self._w_ptr = (ptr + 1) % self.num_buffers
        
        return True

    def read_into(self, target):
        """
        將數據從 HUB 讀出
        ───────────────────────────────────────────────
        :param target: 目標緩衝區 (必須預分配好)
        :return: bool (True: 讀取成功, False: 無數據可讀)
        """
        ptr = self._r_ptr
        
        # 檢查當前指標指向的槽位是否有數據
        if self._status[ptr] != self.READY:
            return False
            
        # 執行高效內存拷貝
        target[:] = self._views[ptr]
        
        # 釋放槽位並更新指標
        self._status[ptr] = self.IDLE
        self._r_ptr = (ptr + 1) % self.num_buffers
        
        return True

    def flush(self):
        """
        快速重設 HUB 狀態
        ───────────────────────────────────────────────
        不動作內存擦除，僅重設指針與狀態機，耗時極短
        """
        for i in range(self.num_buffers):
            self._status[i] = self.IDLE
            
        self._w_ptr = 0
        self._r_ptr = 0

    def get_fill_level(self):
        """
        當前積壓的緩衝數量 (調試用)
        """
        count = 0
        for s in self._status:
            if s == self.READY:
                count += 1
        return count

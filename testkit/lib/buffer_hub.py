# lib/buffer_hub.py
import gc

class AtomicStreamHub:
    """
    極速雙緩衝中心 (High-Performance Dual-Buffering Hub)
    設計目標：
    1. 解決雙核心(Core 0/1)讀寫競爭。
    2. 提供 memoryview 視圖，實現零拷貝數據填充。
    3. 內存預分配，運行期間零 GC 抖動。
    """
    def __init__(self, size):
        # 🚀 物理內存預分配：建立兩塊獨立緩衝區
        self._bufs = [bytearray(size), bytearray(size)]
        # 🚀 視圖緩存：避免運行時重複創建 memoryview 對象
        self._views = [memoryview(b) for b in self._bufs]
        
        # 指針索引：w_idx(寫入/生產), r_idx(讀取/消費)
        self._w_idx = 0
        self._r_idx = 1
        
        # Dirty Flag (紅旗標誌)：代表是否有新數據等待消費
        self.dirty = False
        self.size = size

    def get_write_view(self):
        """
        生產者 (Core 0) 調用：獲取當前可寫入的後台緩衝區。
        """
        return self._views[self._w_idx]

    def commit(self):
        """
        生產者 (Core 0) 調用：提交數據，瞬間交換讀寫指針。
        執行後，剛才寫入的數據對消費者變為可見。
        """
        self._w_idx, self._r_idx = self._r_idx, self._w_idx
        self.dirty = True

    def get_read_view(self):
        """
        消費者 (Core 1) 調用：嘗試獲取最新展示數據。
        若無新數據 (dirty=False)，返回 None。
        """
        if self.dirty:
            self.dirty = False # 🚀 消費者看見紅旗後，立刻收起紅旗
            return self._views[self._r_idx]
        return None

    def force_get_view(self):
        """
        強制獲取當前讀取緩衝區 (無視 dirty 位)。
        用於某些需要持續刷燈而不在乎數據是否更新的場景。
        """
        return self._views[self._r_idx]
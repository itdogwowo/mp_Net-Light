# lib/buffer_hub.py
import gc

class AtomicStreamHub:
    """雙緩衝指針交換中心：解決核心 0 寫入與核心 1 讀取衝突"""
    def __init__(self, size):
        # 預分配兩塊內存，避免運行時產生碎片
        self._bufs = [bytearray(size), bytearray(size)]
        self._w_idx = 0
        self._r_idx = 1
        self.dirty = False
        # 建立內存視圖 memoryview，提速賦值操作
        self._views = [memoryview(b) for b in self._bufs]

    def get_write_view(self):
        """生產者 (Core 0) 獲取當前可寫入的 Buffer 視圖"""
        return self._views[self._w_idx]

    def commit(self):
        """生產者寫完後提交：極速交換讀寫指針"""
        self._w_idx, self._r_idx = self._r_idx, self._w_idx
        self.dirty = True

    def get_read_view(self):
        """消費者 (Core 1) 獲取最新展示數據：無新數據返回 None"""
        if self.dirty:
            self.dirty = False
            return self._views[self._r_idx]
        return None
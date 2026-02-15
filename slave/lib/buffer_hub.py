# lib/buffer_hub.py
"""
AtomicStreamHub - 動態規模緩衝管理器
═══════════════════════════════════════════════════════
支持兩種模式:
1. 全內存模式: 單次分配整個文件大小
2. 滾動緩衝模式: 固定數量的小緩衝塊
"""
import gc

class AtomicStreamHub:
    IDLE = 0
    READY = 1

    def __init__(self, size, num_buffers=8):
        """
        :param size: 每個緩衝區的大小 (bytes)
        :param num_buffers: 緩衝區數量
        """
        self._bufs = [bytearray(size) for _ in range(num_buffers)]
        self._views = [memoryview(b) for b in self._bufs]
        
        # 🔥 新增: offset 追蹤 (用於精確 ACK)
        self._offsets = [0] * num_buffers
        
        self._status = [self.IDLE] * num_buffers
        self._w_ptr = 0
        self._r_ptr = 0
        
        self.size = size
        self.num_buffers = num_buffers
        
        print(f"🚀 [BufferHub] Rolling Mode: {(size * num_buffers) // 1024} KB")

    def write_from(self, source, offset=0):
        """
        寫入數據
        :param source: 來源數據
        :param offset: 文件偏移量 (用於 ACK)
        :return: bool
        """
        ptr = self._w_ptr
        
        if self._status[ptr] != self.IDLE:
            return False
        
        # 拷貝數據
        data_len = len(source)
        self._views[ptr][:data_len] = source
        
        # 🔥 記錄 offset 和實際長度
        self._offsets[ptr] = offset
        
        self._status[ptr] = self.READY
        self._w_ptr = (ptr + 1) % self.num_buffers
        
        return True

    def read_into(self, target):
        """
        讀出數據
        :return: (success: bool, offset: int, length: int)
        """
        ptr = self._r_ptr
        
        if self._status[ptr] != self.READY:
            return False, 0, 0
        
        # 拷貝數據
        data_len = min(len(target), self.size)
        target[:data_len] = self._views[ptr][:data_len]
        
        offset = self._offsets[ptr]
        
        self._status[ptr] = self.IDLE
        self._r_ptr = (ptr + 1) % self.num_buffers
        
        return True, offset, data_len

    def get_fill_level(self):
        """當前積壓數量"""
        return sum(1 for s in self._status if s == self.READY)
    
    def is_full(self):
        """檢查是否已滿"""
        return self._status[self._w_ptr] != self.IDLE
    
    def is_empty(self):
        """檢查是否為空"""
        return self._status[self._r_ptr] != self.READY

    def flush(self):
        """重置所有狀態"""
        for i in range(self.num_buffers):
            self._status[i] = self.IDLE
        self._w_ptr = 0
        self._r_ptr = 0
        
    def free(self):
        """釋放內存"""
        self._bufs = None
        self._views = None
        gc.collect()
        print("♻️ [BufferHub] Memory Released")


class FullMemoryBuffer:
    """
    全內存模式緩衝器
    ═══════════════════════════════════════════════════════
    一次性分配整個文件大小，零拷貝設計
    """
    def __init__(self, total_size):
        self.buffer = bytearray(total_size)
        self.view = memoryview(self.buffer)
        self.total_size = total_size
        self.written = 0
        
        print(f"🚀 [FullMemoryBuffer] Allocated: {total_size // 1024} KB")
    
    def write_at(self, offset, data):
        """
        寫入指定偏移量
        :param offset: 文件偏移
        :param data: 數據
        :return: bool
        """
        data_len = len(data)
        
        if offset + data_len > self.total_size:
            return False
        
        # 🔥 零拷貝寫入
        self.view[offset : offset + data_len] = data
        
        # 更新最大寫入位置
        if offset + data_len > self.written:
            self.written = offset + data_len
        
        return True
    
    def get_progress(self):
        """獲取寫入進度"""
        return (self.written / self.total_size) * 100 if self.total_size > 0 else 0
    
    def get_buffer(self):
        """獲取完整緩衝區"""
        return self.buffer
    
    def free(self):
        """釋放內存"""
        self.buffer = None
        self.view = None
        gc.collect()
        print("♻️ [FullMemoryBuffer] Memory Released")
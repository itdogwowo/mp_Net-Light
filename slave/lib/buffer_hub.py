import gc
import micropython

# 定義常量 (MicroPython 會優化這些)
_IDLE = micropython.const(0)
_READY = micropython.const(1)
_READING = micropython.const(2)

from array import array

class AtomicStreamHub:
    # 槽位狀態 (公開常量供外部參考，但內部使用 _IDLE 等以獲取 native 優化)
    IDLE = _IDLE
    READY = _READY
    READING = _READING

    def __init__(self, size, num_buffers=3, name="Hub"):
        """
        :param size: 每個緩衝區的大小 (bytes)
        :param num_buffers: 緩衝區數量 (推薦 3)
        :param name: 用於調試的名稱
        """
        self.name = name
        # ── 預分配物理緩衝 ──
        self._bufs = [bytearray(size) for _ in range(num_buffers)]
        # ── 預分配視圖 (核心優化：避免運行時創建 view) ──
        self._views = [memoryview(b) for b in self._bufs]
        
        # ── 狀態控制 ──
        # 使用 bytearray 而不是 list 來存儲狀態，以獲得更好的緩存局部性和原子性
        self._status = bytearray(num_buffers) # 0:IDLE, 1:READY, 2:READING
        
        # 🚀 新增：記錄每個 Buffer 的有效長度 (unsigned short array)
        self._lengths = array('H', [0] * num_buffers)
        
        self._w_ptr = 0  # 寫入指標
        self._r_ptr = 0  # 讀取指標
        
        self.size = size
        self.num_buffers = num_buffers
        
        # 記錄上一次被 get_read_view 鎖定的 buffer index
        self._last_read_idx = None
        
        # 預先格式化診斷信息，避免運行時組裝字串
        print(f"🚀 [{name}] Ready: {(size * num_buffers) // 1024} KB total")

    @property
    def dirty(self):
        """
        兼容舊 API：檢查是否有數據可讀
        """
        return self._status[self._r_ptr] == _READY

    @micropython.native
    def write_from(self, source):
        """
        將數據寫入 HUB (複製模式)
        """
        ptr = self._w_ptr
        
        # 檢查當前指標指向的槽位是否可寫入
        if self._status[ptr] != _IDLE:
            return False
        
        slen = len(source)
        view = self._views[ptr]
        blen = len(view)
        
        # 記錄長度
        actual_len = slen if slen <= blen else blen
        
        if slen > blen:
            view[:] = source[:blen]
        else:
            view[:slen] = source
        
        self._lengths[ptr] = actual_len
        
        # 更新狀態與指標
        self._status[ptr] = _READY
        self._w_ptr = (ptr + 1) % self.num_buffers
        
        return True

    @micropython.native
    def read_into(self, target):
        """
        將數據從 HUB 讀出 (複製模式)
        """
        if self._last_read_idx is not None:
             self._status[self._last_read_idx] = _IDLE
             self._last_read_idx = None

        ptr = self._r_ptr
        
        if self._status[ptr] != _READY:
            return False
            
        # 執行高效內存拷貝，只拷貝有效長度
        valid_len = self._lengths[ptr]
        tlen = len(target)
        copy_len = valid_len if valid_len <= tlen else tlen
        
        target[:copy_len] = self._views[ptr][:copy_len]
        
        self._status[ptr] = _IDLE
        self._r_ptr = (ptr + 1) % self.num_buffers
        
        return True
    
    @micropython.native
    def flush(self):
        """
        快速重設 HUB 狀態
        """
        for i in range(self.num_buffers):
            self._status[i] = _IDLE
            self._lengths[i] = 0
            
        self._w_ptr = 0
        self._r_ptr = 0
        self._last_read_idx = None

    def get_fill_level(self):
        """
        當前積壓的緩衝數量 (調試用)
        """
        count = 0
        for s in self._status:
            if s == _READY:
                count += 1
        return count

    @micropython.native
    def get_write_view(self):
        """
        獲取寫入視圖 (零拷貝模式)
        """
        ptr = self._w_ptr
        if self._status[ptr] != _IDLE:
            return None
        return self._views[ptr]

    @micropython.native
    def commit(self, length=0):
        """
        提交寫入
        :param length: 實際寫入的字節數 (0 表示滿)
        """
        ptr = self._w_ptr
        if self._status[ptr] == _IDLE:
            if length <= 0 or length > self.size:
                self._lengths[ptr] = self.size
            else:
                self._lengths[ptr] = length
                
            self._status[ptr] = _READY
            self._w_ptr = (ptr + 1) % self.num_buffers
    
    @micropython.native
    def get_read_view(self):
        """
        獲取讀取視圖 (零拷貝模式)
        返回: (memoryview, length) 元組 (注意：API 變更)
        或者：為了兼容性，只返回 view，但 caller 需要知道長度
        
        ⚠️ API Change: Now returns a sliced memoryview of VALID data
        """
        # 1. 釋放上一個 READING 的 buffer
        if self._last_read_idx is not None:
            self._status[self._last_read_idx] = _IDLE
            self._last_read_idx = None

        # 2. 檢查是否有新數據
        ptr = self._r_ptr
        if self._status[ptr] == _READY:
            self._status[ptr] = _READING
            self._last_read_idx = ptr
            self._r_ptr = (ptr + 1) % self.num_buffers
            
            # 返回切片後的 view，這樣長度就是正確的
            valid_len = self._lengths[ptr]
            return self._views[ptr][:valid_len]
        
        return None
    
    def force_get_view(self):
        """
        強制獲取當前讀取指針的視圖 (不論狀態)
        用於調試或特殊場景
        """
        return self._views[self._r_ptr]

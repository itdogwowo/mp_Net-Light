# lib/buffer_hub.py
"""
AtomicStreamHub - 通用多緩衝管理器
═══════════════════════════════════════════════════════
設計理念:
- 只管理槽位狀態,不存儲業務數據
- 只提供索引,外部自行維護業務邏輯
- 高效能: 全部 O(1) 操作
"""

class AtomicStreamHub:
    """
    通用多緩衝管理器
    ───────────────────────────────────────────────────
    職責:
    1. 管理 N 個 Buffer 的分配與回收
    2. 維護讀寫順序 (next_index 邏輯)
    3. 提供 memoryview 零拷貝視圖
    
    不負責:
    - 不知道 Buffer 內容
    - 不知道業務邏輯
    - 不做數據解析
    """
    
    # ══════════════════════════════════════════════════
    # 槽位狀態常量
    # ══════════════════════════════════════════════════
    IDLE = 0       # 閒置,可分配
    LOADING = 1    # 正在寫入
    READY = 2      # 已就緒,可讀取
    PLAYING = 3    # 正在讀取
    
    def __init__(self, size, num_buffers=3):
        """
        初始化
        ───────────────────────────────────────────────
        參數:
            size: 每個 Buffer 的大小 (bytes)
            num_buffers: Buffer 數量 (建議 2-3)
        """
        # ── 物理 Buffer ──
        self._bufs = [bytearray(size) for _ in range(num_buffers)]
        self._views = [memoryview(b) for b in self._bufs]
        
        # ── 槽位狀態 (極簡) ──
        self._status = [self.IDLE] * num_buffers
        self._last_used = [0] * num_buffers  # LRU 時間戳
        
        # ── 寫入狀態 ──
        self._write_index = -1
        
        # ── 讀取狀態 ──
        self._play_index = -1
        self._next_index = -1
        
        self.size = size
        self.num_buffers = num_buffers
        
        print(f"🚀 [BufferHub] {num_buffers} × {size // 1024} KB = {size * num_buffers // 1024} KB total")
    
    # ══════════════════════════════════════════════════
    # 寫入 API (Core 0)
    # ══════════════════════════════════════════════════
    
    def get_write_view(self):
        """
        獲取可寫槽位
        ───────────────────────────────────────────────
        返回:
            (index, memoryview) 或 (None, None)
        
        邏輯:
        - 尋找 IDLE 槽位 (LRU)
        - 標記為 LOADING
        - 返回槽位索引與視圖
        """
        # 尋找 IDLE 槽位
        idle_slots = []
        for i in range(self.num_buffers):
            if self._status[i] == self.IDLE:
                idle_slots.append((i, self._last_used[i]))
        
        if not idle_slots:
            return (None, None)
        
        # LRU: 選擇最久未用
        idle_slots.sort(key=lambda x: x[1])
        idx = idle_slots[0][0]
        
        # 標記為 LOADING
        self._status[idx] = self.LOADING
        self._write_index = idx
        
        return (idx, self._views[idx])
    
    def commit(self):
        """
        提交寫入完成
        ───────────────────────────────────────────────
        返回:
            slot_index 或 None
        
        邏輯:
        - 標記為 READY
        - 若 next_index = -1,自動設為此槽位
        - 返回槽位索引 (供外部記錄業務數據)
        """
        if self._write_index == -1:
            return None
        
        idx = self._write_index
        
        # 標記為 READY
        self._status[idx] = self.READY
        self._last_used[idx] = self._get_time()
        
        # 若無下一個,自動設為此槽位
        if self._next_index == -1:
            self._next_index = idx
        
        # 釋放寫入鎖
        self._write_index = -1
        
        return idx
    
    # ══════════════════════════════════════════════════
    # 讀取 API (Core 1)
    # ══════════════════════════════════════════════════
    
    def has_next(self):
        """
        檢查是否有下一個可讀槽位
        ───────────────────────────────────────────────
        返回:
            True / False
        """
        return self._next_index != -1
    
    def get_read_view(self):
        """
        獲取當前讀取槽位
        ───────────────────────────────────────────────
        返回:
            (index, memoryview) 或 (None, None)
        
        邏輯:
        - 若 play_index = -1,切換到 next_index
        - 返回當前播放槽位的索引與視圖
        """
        # 若無當前播放槽位,切換到 next
        if self._play_index == -1:
            if not self._switch_to_next():
                return (None, None)
        
        return (self._play_index, self._views[self._play_index])
    
    def release(self):
        """
        釋放當前讀取槽位
        ───────────────────────────────────────────────
        邏輯:
        - 標記為 IDLE
        - 更新 next_index (順序: current+1)
        - 重置 play_index
        """
        if self._play_index == -1:
            return
        
        # 標記為 IDLE
        self._status[self._play_index] = self.IDLE
        self._last_used[self._play_index] = self._get_time()
        
        # 更新 next_index (順序播放)
        next_candidate = (self._play_index + 1) % self.num_buffers
        if self._status[next_candidate] == self.READY:
            self._next_index = next_candidate
        else:
            # 尋找下一個 READY 槽位
            self._next_index = self._find_next_ready()
        
        # 重置播放索引
        self._play_index = -1
    
    # ══════════════════════════════════════════════════
    # 控制 API
    # ══════════════════════════════════════════════════
    
    def set_next(self, index):
        """
        設定下一個讀取槽位 (插隊/跳轉)
        ───────────────────────────────────────────────
        參數:
            index: 槽位索引 或 -1 (無下一個)
        
        返回:
            True / False
        """
        if index == -1:
            self._next_index = -1
            return True
        
        if 0 <= index < self.num_buffers:
            self._next_index = index
            return True
        
        return False
    
    def get_slot_status(self, index):
        """
        查詢槽位狀態
        ───────────────────────────────────────────────
        參數:
            index: 槽位索引
        
        返回:
            IDLE / LOADING / READY / PLAYING 或 None
        """
        if 0 <= index < self.num_buffers:
            return self._status[index]
        return None
    
    # ══════════════════════════════════════════════════
    # 內部方法
    # ══════════════════════════════════════════════════
    
    def _switch_to_next(self):
        """切換到 next_index 指定的槽位"""
        if self._next_index == -1:
            return False
        
        if not (0 <= self._next_index < self.num_buffers):
            self._next_index = -1
            return False
        
        # 驗證狀態
        if self._status[self._next_index] != self.READY:
            # 槽位不可用,嘗試尋找下一個
            self._next_index = self._find_next_ready()
            if self._next_index == -1:
                return False
        
        # 標記為 PLAYING
        self._status[self._next_index] = self.PLAYING
        self._play_index = self._next_index
        
        # 計算新的 next_index (順序)
        next_candidate = (self._play_index + 1) % self.num_buffers
        if self._status[next_candidate] == self.READY:
            self._next_index = next_candidate
        else:
            self._next_index = -1
        
        return True
    
    def _find_next_ready(self):
        """尋找下一個 READY 槽位"""
        start = (self._play_index + 1) % self.num_buffers if self._play_index != -1 else 0
        
        for i in range(self.num_buffers):
            idx = (start + i) % self.num_buffers
            if self._status[idx] == self.READY:
                return idx
        
        return -1
    
    def _get_time(self):
        """獲取時間戳 (ms)"""
        import time
        return time.ticks_ms()
    
    # ══════════════════════════════════════════════════
    # 診斷 API
    # ══════════════════════════════════════════════════
    
    def get_status(self):
        """獲取所有槽位狀態 (調試用)"""
        status_map = {
            self.IDLE: "IDLE",
            self.LOADING: "LOADING",
            self.READY: "READY",
            self.PLAYING: "PLAYING"
        }
        
        return {
            "slots": [
                {"index": i, "status": status_map[self._status[i]]}
                for i in range(self.num_buffers)
            ],
            "play_index": self._play_index,
            "next_index": self._next_index,
            "write_index": self._write_index
        }
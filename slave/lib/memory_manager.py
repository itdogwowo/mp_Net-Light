import gc
import micropython
from lib.globalMethod import debugPrint

class MemoryManager:
    """
    PSRAM 動態資源管理器
    針對大內存設備 (如 ESP32-P4 32MB PSRAM) 優化
    職責：
    1. 監控系統可用內存
    2. 提供大塊緩衝區的動態租賃 (Rental)
    3. 防止內存耗盡 (OOM)
    """
    
    # 單例模式實例
    _instance = None
    
    @classmethod
    def get(cls):
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    def __init__(self, reserved_mb=4):
        """
        reserved_mb: 保留給系統堆疊和 MicroPython 運作的內存 (默認 4MB)
        對於 32MB 設備，這意味著我們有約 28MB 可用於動態分配
        """
        self.reserved_bytes = reserved_mb * 1024 * 1024
        
    def info(self):
        """打印當前內存狀態"""
        gc.collect()
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        total = free + alloc
        debugPrint(f"🧠 [Mem] Total: {total/1024/1024:.2f}MB | Free: {free/1024/1024:.2f}MB | Alloc: {alloc/1024/1024:.2f}MB")
        return free

    def rent_buffer(self, size_hint, hard_limit=16*1024*1024, align=4096):
        """
        租用緩衝區 (Rent a Buffer)
        
        Args:
            size_hint: 期望大小 (bytes)
            hard_limit: 硬性上限 (默認 16MB)
            align: 對齊字節 (默認 4KB，利於 DMA)
            
        Returns:
            bytearray: 分配到的緩衝區 (可能小於期望值，但盡量大)
        """
        gc.collect()
        free = gc.mem_free()
        
        # 計算安全可用空間 (Safe Available)
        safe_avail = free - self.reserved_bytes
        if safe_avail < 0: safe_avail = 0
        
        # 決策分配大小
        # 1. 不超過硬性上限
        # 2. 不超過期望大小
        # 3. 不超過安全可用空間
        alloc_size = min(size_hint, hard_limit, safe_avail)
        
        # 如果計算出來太小 (例如小於 64KB)，但還有不少 Free RAM
        # 則嘗試分配 Free 的 50% 作為保底，除非 Free 真的很少
        if alloc_size < 64 * 1024:
            alloc_size = free // 2
            
        # 對齊處理 (向下取整)
        alloc_size = (alloc_size // align) * align
        if alloc_size < align: alloc_size = align # 至少分配一個塊
        
        try:
            buf = bytearray(alloc_size)
            debugPrint(f"✅ [Mem] Rented {len(buf)/1024:.1f} KB (Req: {size_hint/1024:.1f} KB)")
            return buf
        except MemoryError:
            # 如果因為碎片化導致分配失敗，嘗試減半重試
            debugPrint(f"⚠️ [Mem] Fragmented! Retrying half size...")
            try:
                buf = bytearray(alloc_size // 2)
                return buf
            except:
                debugPrint(f"❌ [Mem] Allocation Failed!")
                return bytearray(1024) # 最終保底 1KB，避免程式崩潰

    def rent_max(self, hard_limit=16*1024*1024):
        """
        租用「最大可用」緩衝區 (All-In 模式)
        適用於：大文件哈希計算、批量數據處理
        """
        # 請求一個超大數值，讓 rent_buffer 自動計算上限
        return self.rent_buffer(hard_limit, hard_limit=hard_limit)

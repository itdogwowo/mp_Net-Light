# fast_ram_fs_v3.py
# 終極優化版 FastRamFS (v3) - 放棄 VFS，擁抱 Buffer Protocol
# 1. 不使用 mount，不模擬文件系統
# 2. 直接操作 bytearray 
# 3. 提供類文件接口供 FileRx 使用

import micropython

class RamBufferFile:
    def __init__(self, buffer):
        self.buffer = buffer # pre-allocated bytearray or memoryview
        self.pos = 0
        self.len = len(buffer)
        
    @micropython.native
    def write(self, data):
        # 這是最關鍵的優化：
        # 1. 避免創建 memoryview 切片 (這會產生小對象)
        # 2. 避免邊界檢查 (假設調用者知道自己在做什麼)
        # 3. 使用 native emitter
        
        l = len(data)
        if self.pos + l > self.len:
            return 0 # Error
            
        # 這裡仍然是 Python 層面的拷貝，但因為是 native，會快很多
        # 如果這還是慢，那就真的是 MicroPython 的極限了
        self.buffer[self.pos : self.pos + l] = data
        self.pos += l
        return l

    @micropython.native
    def readinto(self, buf):
        l = len(buf)
        if self.pos + l > self.len:
            l = self.len - self.pos
        
        buf[:l] = self.buffer[self.pos : self.pos + l]
        self.pos += l
        return l

    def seek(self, off):
        self.pos = off
        
    def close(self):
        pass

# 全局單例 Buffer 管理器
class RamBufferManager:
    def __init__(self, size_kb=1024):
        print(f"Allocating RamBuffer: {size_kb} KB...")
        self.data = bytearray(size_kb * 1024)
        self.mv = memoryview(self.data)
        
    def open(self, path, mode="wb"):
        # 忽略 path，永遠返回同一個 buffer 的包裝器
        # 每次 open 都重置指針
        f = RamBufferFile(self.mv)
        if "w" in mode:
            f.pos = 0
        return f


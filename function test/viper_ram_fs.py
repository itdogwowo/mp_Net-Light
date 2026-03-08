# viper_ram_fs.py
# 基於 Viper Emitter 的極速 RAM Disk
# 繞過 MicroPython Slice Assignment 瓶頸

import micropython
import uctypes

# 定義 Viper 函數 (必須在全域)
@micropython.viper
def _viper_memcpy_offset(dest_ptr: ptr8, dest_offset: int, src_ptr: ptr8, count: int):
    # 指針運算：dest_ptr + dest_offset
    # 注意：Viper 中指針索引是 base[index]
    p_dest = dest_ptr
    p_src = src_ptr
    for i in range(count):
        p_dest[dest_offset + i] = p_src[i]

class ViperRamFile:
    def __init__(self, buffer_addr, buffer_len):
        self.buffer_addr = buffer_addr # 緩衝區起始地址 (int)
        self.buffer_len = buffer_len
        self.pos = 0
        self.size = 0
        
    def write(self, data):
        # 獲取數據的地址和長度
        # 如果 data 是 bytes/bytearray/memoryview
        # uctypes.addressof 可以處理
        
        # 優化：假設 data 已經是 memoryview 或 bytes
        l = len(data)
        if self.pos + l > self.buffer_len:
            raise OSError(28) # ENOSPC
            
        src_addr = uctypes.addressof(data)
        
        # 調用 Viper 函數進行拷貝
        # 這裡 dest_addr 已經是 int，直接傳入
        # 注意：Viper 函數的參數類型轉換會自動處理 int -> ptr8 (如果是指針參數)
        # 但在調用時，我們需要確保傳入的是整數地址
        
        # 為了安全，這裡做個轉型檢查
        # _viper_memcpy_offset(int(self.buffer_addr), int(self.pos), int(src_addr), int(l))
        # 實際上 viper 函數參數定義為 ptr8，傳入 int 會被視為地址
        _viper_memcpy_offset(self.buffer_addr, self.pos, src_addr, l)
        
        self.pos += l
        if self.pos > self.size:
            self.size = self.pos
        return l

    def read(self, n=-1):
        # 讀取部分不需要極致優化，因為校驗是計算密集型
        # 如果需要，可以用 memoryview 切片 (讀取切片比寫入切片快)
        # 為了相容性，這裡需要一個能夠訪問 raw memory 的方法
        # 最簡單的是保存一個 memoryview 引用
        pass 
        # (註：由於 Viper 主要是為了解決寫入瓶頸，讀取可以用標準方法)

    def seek(self, off, whence=0):
        if whence == 0: self.pos = off
        elif whence == 1: self.pos += off
        elif whence == 2: self.pos = self.size + off
        return self.pos

    def close(self): pass

class ViperRamManager:
    def __init__(self, size_kb=1024):
        print(f"Allocating ViperRamBuffer: {size_kb} KB...")
        self.data = bytearray(size_kb * 1024)
        # 獲取緩衝區的物理地址
        self.addr = uctypes.addressof(self.data)
        self.len = len(self.data)
        # 同時保留 memoryview 用於讀取
        self.mv = memoryview(self.data)
        
    def open(self, path, mode="wb"):
        f = ViperRamFile(self.addr, self.len)
        # 把 memoryview 塞進去給 read 用 (如果需要)
        f.mv = self.mv 
        
        # 補上 read 方法 (使用 memoryview)
        def read(n=-1):
            if n == -1: n = f.size - f.pos
            if f.pos + n > f.size: n = f.size - f.pos
            if n <= 0: return b""
            res = bytes(f.mv[f.pos : f.pos + n])
            f.pos += n
            return res
        
        def readinto(buf):
            n = len(buf)
            if f.pos + n > f.size: n = f.size - f.pos
            if n <= 0: return 0
            buf[:n] = f.mv[f.pos : f.pos + n]
            f.pos += n
            return n
            
        f.read = read
        f.readinto = readinto
        
        if "w" in mode:
            f.pos = 0
        return f

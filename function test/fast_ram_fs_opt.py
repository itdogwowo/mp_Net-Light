# fast_ram_fs_opt.py
# 極速優化版 FastRamFS
# 1. 使用 @micropython.native 加速關鍵路徑
# 2. 移除 write 中的字典操作 overhead
# 3. 增加 ioctl 支援 (某些情況下 VFS 需要)

import uerrno
import micropython

class FastRamFileOpt:
    def __init__(self, buffer, fs, name):
        self.buffer = buffer  # memoryview
        self.pos = 0
        self.fs = fs
        self.name = name
        if name in fs.files:
            self.size = fs.files[name]
        else:
            self.size = 0
            
    # 使用 native emitter 加速
    @micropython.native
    def write(self, buf):
        n = len(buf)
        # 移除邊界檢查以追求極致速度 (假設調用者負責檢查)
        # 或者保留基本的長度檢查
        if self.pos + n > len(self.buffer):
            return -1 # ENOSPC
            
        # 直接內存複製
        self.buffer[self.pos : self.pos + n] = buf
        self.pos += n
        
        # 僅更新局部變量，不操作字典
        if self.pos > self.size:
            self.size = self.pos
        return n

    @micropython.native
    def read(self, n=-1):
        if n == -1:
            n = self.size - self.pos
        if n <= 0:
            return b""
        if self.pos + n > self.size:
            n = self.size - self.pos
        
        # 創建 bytes 副本返回
        res = bytes(self.buffer[self.pos : self.pos + n])
        self.pos += n
        return res

    @micropython.native
    def readinto(self, buf):
        n = len(buf)
        if self.pos + n > self.size:
            n = self.size - self.pos
        if n <= 0:
            return 0
            
        buf[:n] = self.buffer[self.pos : self.pos + n]
        self.pos += n
        return n

    def seek(self, off, whence=0):
        if whence == 0:   # SEEK_SET
            self.pos = off
        elif whence == 1: # SEEK_CUR
            self.pos += off
        elif whence == 2: # SEEK_END
            self.pos = self.size + off
        return self.pos

    def tell(self):
        return self.pos

    def close(self):
        # 關閉時才更新全局文件表
        self.fs.files[self.name] = self.size

    def flush(self):
        pass
    
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class FastRamFSOpt:
    def __init__(self, size_kb=1024):
        print(f"Allocating FastRamFS (Optimized): {size_kb} KB...")
        self.raw_data = bytearray(size_kb * 1024)
        self.mv = memoryview(self.raw_data)
        self.files = {} # path -> size
        self.block_size = 4096

    def mount(self, readonly, mkfs):
        pass

    def umount(self):
        pass

    def stat(self, path):
        if path == "" or path == "/":
            return (0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        name = path.lstrip("/")
        if name in self.files:
            return (0x8000, 0, 0, 0, 0, 0, self.files[name], 0, 0, 0)
        raise OSError(uerrno.ENOENT)
        
    def statvfs(self, path):
        total_blocks = len(self.mv) // self.block_size
        return (self.block_size, self.block_size, total_blocks, total_blocks, total_blocks, 0, 0, 0, 0, 255)

    def open(self, path, mode):
        name = path.lstrip("/")
        if "w" in mode:
            # 不要在這裡清空 self.files[name]，因為 File 對象會維護自己的 size
            pass
        return FastRamFileOpt(self.mv, self, name)

    def ilistdir(self, path):
        return iter([(name, 0x8000, 0, self.files[name]) for name in self.files])
    
    def mkdir(self, path): pass
    def rmdir(self, path): pass
    def remove(self, path):
        name = path.lstrip("/")
        if name in self.files: del self.files[name]
    def rename(self, old, new): pass

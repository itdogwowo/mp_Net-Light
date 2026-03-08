# fast_ram_fs.py
# 專為 MicroPython 設計的極速 RAM VFS (繞過 FAT overhead)
# 支援單一大文件緩衝，實現 memcpy 級別的寫入速度

import uerrno
import uos

class FastRamFile:
    def __init__(self, buffer, fs, name):
        self.buffer = buffer  # memoryview of the global buffer
        self.pos = 0
        self.fs = fs
        self.name = name
        # 預設指向當前文件大小 (如果是 append)
        if name in fs.files:
            self.size = fs.files[name]
        else:
            self.size = 0
            fs.files[name] = 0

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

    def readinto(self, buf):
        n = len(buf)
        if self.pos + n > self.size:
            n = self.size - self.pos
        if n <= 0:
            return 0
            
        # 直接內存複製
        buf[:n] = self.buffer[self.pos : self.pos + n]
        self.pos += n
        return n

    def write(self, buf):
        n = len(buf)
        # 檢查溢出
        if self.pos + n > len(self.buffer):
            raise OSError(uerrno.ENOSPC)
            
        # 極速寫入：直接操作 memoryview
        self.buffer[self.pos : self.pos + n] = buf
        self.pos += n
        
        # 更新文件大小
        if self.pos > self.size:
            self.size = self.pos
            self.fs.files[self.name] = self.size
        return n

    def seek(self, off, whence=0):
        if whence == 0:   # SEEK_SET
            self.pos = off
        elif whence == 1: # SEEK_CUR
            self.pos += off
        elif whence == 2: # SEEK_END
            self.pos = self.size + off
        
        # 邊界檢查
        if self.pos < 0: self.pos = 0
        if self.pos > self.size: self.pos = self.size
        return self.pos

    def tell(self):
        return self.pos

    def close(self):
        pass

    def flush(self):
        pass
    
    # 支持 context manager
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class FastRamFS:
    def __init__(self, size_kb=1024):
        print(f"Allocating FastRamFS: {size_kb} KB...")
        self.raw_data = bytearray(size_kb * 1024)
        self.mv = memoryview(self.raw_data)
        self.files = {} # path -> size
        self.block_size = 4096

    def mount(self, readonly, mkfs):
        pass

    def umount(self):
        pass

    def stat(self, path):
        # 模擬 stat 結果: (mode, inode, dev, nlink, uid, gid, size, atime, mtime, ctime)
        # 0x8000 = S_IFREG (常規文件)
        # 0x4000 = S_IFDIR (目錄)
        if path == "" or path == "/":
            return (0x4000, 0, 0, 0, 0, 0, 0, 0, 0, 0)
            
        # 去除前導 /
        name = path.lstrip("/")
        if name in self.files:
            return (0x8000, 0, 0, 0, 0, 0, self.files[name], 0, 0, 0)
        raise OSError(uerrno.ENOENT)
        
    def statvfs(self, path):
        # (bsize, frsize, blocks, bfree, bavail, files, ffree, favail, flag, namemax)
        total_blocks = len(self.mv) // self.block_size
        free_blocks = total_blocks # 簡化計算
        return (self.block_size, self.block_size, total_blocks, free_blocks, free_blocks, 0, 0, 0, 0, 255)

    def open(self, path, mode):
        name = path.lstrip("/")
        # 如果是寫入模式，重置文件大小 (簡化版：所有文件共用一個大 Buffer)
        # 注意：這是一個針對"單一臨時大文件"優化的極簡 VFS
        # 如果需要多文件並存，需要實作記憶體分配器 (malloc)，這會降低效能
        # 這裡假設場景是：一次只處理一個大文件傳輸
        
        if "w" in mode:
            self.files[name] = 0 # Truncate
            
        return FastRamFile(self.mv, self, name)

    def ilistdir(self, path):
        # 列出所有文件
        return iter([(name, 0x8000, 0, self.files[name]) for name in self.files])
    
    def mkdir(self, path):
        pass
        
    def rmdir(self, path):
        pass
        
    def remove(self, path):
        name = path.lstrip("/")
        if name in self.files:
            del self.files[name]
    
    def rename(self, old_path, new_path):
        old_name = old_path.lstrip("/")
        new_name = new_path.lstrip("/")
        if old_name in self.files:
            self.files[new_name] = self.files.pop(old_name)


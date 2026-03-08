# ram_disk_v2.py
# 優化版 RAM Disk 測試 + 記憶體原始效能測試
import uos
import time
import gc
import machine

# 嘗試使用 native emitter 加速函數調用與迴圈
@micropython.native
def memcpy_test(dest, src, count):
    """
    測試純內存拷貝速度
    """
    start = time.ticks_ms()
    for _ in range(count):
        dest[:] = src
    end = time.ticks_ms()
    return time.ticks_diff(end, start)

class RamDiskOpt:
    def __init__(self, block_size=512, blocks=2048):
        self.block_size = block_size
        self.blocks = blocks
        print(f"Allocating RAM Disk: {blocks * block_size / 1024} KB...")
        try:
            self.data = bytearray(block_size * blocks)
            # 關鍵優化：預先創建 memoryview，避免每次調用都創建
            self.mv = memoryview(self.data)
            print("RAM allocation successful.")
        except MemoryError:
            print("Error: Not enough RAM available!")
            raise

    # 使用 native emitter 加速 block 讀取
    @micropython.native
    def readblocks(self, n, buf, off=0):
        # 計算地址
        addr = n * 512 + off  # hardcode 512 for speed if consistent
        length = len(buf)
        # 直接使用預存的 memoryview 進行 slice
        buf[:] = self.mv[addr : addr + length]

    # 使用 native emitter 加速 block 寫入
    @micropython.native
    def writeblocks(self, n, buf, off=0):
        addr = n * 512 + off
        length = len(buf)
        # 直接寫入預存的 memoryview
        self.mv[addr : addr + length] = buf

    def ioctl(self, op, arg):
        if op == 4:  # BP_IOCTL_SEC_COUNT
            return self.blocks
        if op == 5:  # BP_IOCTL_SEC_SIZE
            return self.block_size
        return 0

def run_test():
    print("=== System Info ===")
    print(f"Freq: {machine.freq() / 1000000} MHz")
    gc.collect()
    print(f"Free RAM: {gc.mem_free() / 1024} KB")
    
    # 1. 原始內存拷貝測試 (基準測試)
    print("\n=== Raw Memory Copy Benchmark ===")
    chunk_size = 4096
    total_mb = 10 # 測試拷貝 10MB 數據量
    count = (total_mb * 1024 * 1024) // chunk_size
    
    src = bytearray(chunk_size)
    dest = bytearray(chunk_size) # 在 SRAM/PSRAM 中
    
    print(f"Copying {total_mb} MB in {chunk_size} byte chunks...")
    ms = memcpy_test(dest, src, count)
    speed = total_mb / (ms / 1000)
    print(f"Raw Copy Speed: {speed:.2f} MB/s")
    
    if speed < 1.0:
        print("⚠️ WARNING: Raw memory access is very slow. Check PSRAM config!")

    # 2. RAM Disk 測試
    print("\n=== Optimized RAM Disk Test ===")
    try:
        # 嘗試分配 512KB (1024 blocks)
        bdev = RamDiskOpt(blocks=1024)
    except Exception as e:
        print(f"Setup failed: {e}")
        return

    print("Formatting (FAT)...")
    uos.VfsFat.mkfs(bdev)

    mount_point = "/ram_opt"
    print(f"Mounting at {mount_point}...")
    try:
        uos.mount(bdev, mount_point)
    except Exception:
        try:
            uos.umount(mount_point)
            uos.mount(bdev, mount_point)
        except:
            pass

    # 3. 寫入測試
    print("\n--- VFS Write Speed Test ---")
    test_file = f"{mount_point}/test.bin"
    total_size = 256 * 1024 # 256KB
    data = b'\xAA' * chunk_size
    
    t0 = time.ticks_ms()
    with open(test_file, "wb") as f:
        # 預分配文件大小 (如果支持) - FAT 通常不支持 fallocate，只能 write
        for _ in range(total_size // chunk_size):
            f.write(data)
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_kb = (total_size / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed_kb:.2f} KB/s")

    # 4. 讀取測試
    print("\n--- VFS Read Speed Test ---")
    t0 = time.ticks_ms()
    with open(test_file, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_kb = (total_size / 1024) / (diff / 1000)
    print(f"Read {total_size/1024} KB in {diff} ms")
    print(f"Read Speed: {speed_kb:.2f} KB/s")

    # Cleanup
    try:
        uos.umount(mount_point)
    except:
        pass

if __name__ == "__main__":
    run_test()

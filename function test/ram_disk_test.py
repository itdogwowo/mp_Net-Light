# ram_disk_test.py
# 用於測試 MicroPython VFS 的 RAM Disk 功能
# 請將此文件上傳到 ESP32 並執行
import uos
import time
import gc

class RamDisk:
    def __init__(self, block_size=512, blocks=2048): # 默認 1MB
        self.block_size = block_size
        self.blocks = blocks
        print(f"Allocating RAM Disk: {blocks * block_size / 1024} KB...")
        try:
            self.data = bytearray(block_size * blocks)
            print("RAM allocation successful.")
        except MemoryError:
            print("Error: Not enough RAM available!")
            raise

    def readblocks(self, n, buf, off=0):
        # 使用 memoryview 避免拷貝，極速讀取
        addr = n * self.block_size + off
        length = len(buf)
        buf[:] = memoryview(self.data)[addr : addr + length]

    def writeblocks(self, n, buf, off=0):
        # 使用 memoryview 極速寫入
        addr = n * self.block_size + off
        length = len(buf)
        self.data[addr : addr + length] = buf

    def ioctl(self, op, arg):
        if op == 4:  # BP_IOCTL_SEC_COUNT
            return self.blocks
        if op == 5:  # BP_IOCTL_SEC_SIZE
            return self.block_size
        return 0

def run_test():
    print("=== RAM Disk Performance Test ===")
    
    # 1. 初始化 RAM Disk (1MB)
    # 注意: 如果你的板子沒有 PSRAM，請將 blocks 改小 (例如 64 = 32KB)
    try:
        # 嘗試分配 512KB (1024 blocks * 512 bytes)
        # 如果有 PSRAM，可以嘗試更大，例如 4MB (8192 blocks)
        bdev = RamDisk(blocks=1024) 
    except Exception as e:
        print(f"Setup failed: {e}")
        return

    # 2. 格式化為 FAT 文件系統
    print("Formatting RAM Disk (FAT)...")
    try:
        uos.VfsFat.mkfs(bdev)
    except Exception as e:
        print(f"Format failed: {e}")
        return

    # 3. 掛載到 /ram
    mount_point = "/ram"
    print(f"Mounting at {mount_point}...")
    try:
        uos.mount(bdev, mount_point)
    except Exception as e:
        print(f"Mount failed: {e}")
        # 如果已經掛載過，嘗試卸載後重試
        try:
            uos.umount(mount_point)
            uos.mount(bdev, mount_point)
        except:
            pass

    # 4. 寫入速度測試
    print("\n--- Write Speed Test ---")
    test_file = f"{mount_point}/test.bin"
    chunk_size = 4096 # 4KB chunks
    total_size = 256 * 1024 # 256KB total
    data = b'\xAA' * chunk_size
    
    t0 = time.ticks_ms()
    with open(test_file, "wb") as f:
        for _ in range(total_size // chunk_size):
            f.write(data)
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    speed = (total_size / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed:.2f} KB/s")

    # 5. 讀取與校驗測試
    print("\n--- Read & Verify Test ---")
    t0 = time.ticks_ms()
    with open(test_file, "rb") as f:
        read_data = f.read()
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    speed = (total_size / 1024) / (diff / 1000)
    print(f"Read {len(read_data)/1024} KB in {diff} ms")
    print(f"Read Speed: {speed:.2f} KB/s")
    
    if len(read_data) == total_size and read_data[0] == 0xAA:
        print("✅ Verification: SUCCESS")
    else:
        print("❌ Verification: FAILED")

    # 6. 清理
    print("\n--- Cleanup ---")
    uos.umount(mount_point)
    print("Unmounted.")
    gc.collect()

if __name__ == "__main__":
    run_test()

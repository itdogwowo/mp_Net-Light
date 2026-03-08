# fast_ram_test_v3.py
# 測試 v3: 極簡 Buffer 封裝 (不掛載 VFS)
import time
import gc
import machine
from fast_ram_fs_v3 import RamBufferManager

def run_test():
    print("=== System Info ===")
    print(f"Freq: {machine.freq() / 1000000} MHz")
    gc.collect()
    print(f"Free RAM: {gc.mem_free() / 1024} KB")
    
    # 1. 初始化
    try:
        # 分配 1MB (如果有 PSRAM)，否則請改小
        mgr = RamBufferManager(size_kb=1024) 
    except Exception as e:
        print(f"Alloc failed: {e}")
        return

    chunk_size = 4096 
    total_size = 256 * 1024 # 256KB
    data = b'\xAA' * chunk_size
    # 為了公平，讓 data 也是 memoryview，避免額外轉換
    data_mv = memoryview(data)

    # 2. Write Test
    print("\n--- [V3 Buffer] Write Speed Test ---")
    f = mgr.open("any_name")
    
    t0 = time.ticks_ms()
    # 模擬 FileRx 寫入循環
    for _ in range(total_size // chunk_size):
        f.write(data_mv) # 傳入 memoryview
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed_mb:.2f} MB/s")

    # 3. Read Test
    print("\n--- [V3 Buffer] Read Speed Test ---")
    f.seek(0)
    read_buf = bytearray(chunk_size)
    read_mv = memoryview(read_buf)
    
    t0 = time.ticks_ms()
    while True:
        n = f.readinto(read_mv)
        if n == 0: break
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Read {total_size/1024} KB in {diff} ms")
    print(f"Read Speed: {speed_mb:.2f} MB/s")

if __name__ == "__main__":
    run_test()

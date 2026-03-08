# fast_ram_test_v4.py
# 測試 v4: 隔離測試 - 預先生成數據 vs 即時生成
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
    mgr = RamBufferManager(size_kb=1024) 
    f = mgr.open("test")

    chunk_size = 4096 
    total_size = 256 * 1024 # 256KB
    
    # 預先生成一個巨大的 List of MemoryViews，模擬「數據已經準備好」的場景
    # 這可以排除「數據生成/切片」造成的干擾
    print("\n--- Pre-allocating Data Chunks ---")
    chunks = []
    base_data = b'\xAA' * chunk_size
    base_mv = memoryview(base_data)
    
    count = total_size // chunk_size
    for _ in range(count):
        chunks.append(base_mv)
    print(f"Prepared {len(chunks)} chunks.")

    # 2. 純寫入循環 (排除生成開銷)
    print("\n--- [Pure Write] Speed Test ---")
    
    t0 = time.ticks_ms()
    for chunk in chunks:
        f.write(chunk)
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed_mb:.2f} MB/s")

    # 3. 對照組：即時生成
    print("\n--- [Generate + Write] Speed Test ---")
    f.seek(0)
    
    t0 = time.ticks_ms()
    for _ in range(count):
        # 模擬每次都創建新的 bytes 對象
        # 這會觸發大量 GC 和內存分配
        data = b'\xAA' * chunk_size 
        f.write(data)
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed_mb:.2f} MB/s")

if __name__ == "__main__":
    run_test()

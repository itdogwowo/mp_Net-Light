# viper_ram_test.py
# 測試 ViperRamFS
import time
import gc
import machine
import micropython
import uctypes

# 在測試腳本中定義 Viper 函數，因為它需要直接訪問
# 但我們的 FS 封裝已經處理了。這裡為了測試，需要引入 FS
from viper_ram_fs import ViperRamManager, _viper_memcpy_offset

def run_test():
    print("=== System Info ===")
    print(f"Freq: {machine.freq() / 1000000} MHz")
    gc.collect()
    print(f"Free RAM: {gc.mem_free() / 1024} KB")
    
    # 1. 初始化
    try:
        mgr = ViperRamManager(size_kb=1024)
    except Exception as e:
        print(f"Alloc failed: {e}")
        return

    chunk_size = 4096 
    total_size = 256 * 1024 # 256KB
    
    # 預備數據 (為了測試寫入速度，我們需要準備多個 chunk 的地址)
    # 在真實場景中，NetBus 接收到的數據就在某個緩衝區中
    # 這裡我們預先創建這些緩衝區
    print("Pre-allocating source chunks...")
    src_data = b'\xAA' * chunk_size
    # 獲取源數據地址
    src_addr = uctypes.addressof(src_data)
    
    # 2. Viper Write Test
    print("\n--- [ViperRamFS] Write Speed Test ---")
    f = mgr.open("test.bin", "wb")
    
    t0 = time.ticks_ms()
    # 模擬循環寫入
    # 注意：我們傳入的是同一個對象，但在 FS 內部每次都會計算地址並調用 viper
    # 這是為了模擬真實的函數調用開銷
    for _ in range(total_size // chunk_size):
        # 這裡我們傳入 src_data 對象
        # ViperRamFile.write 會調用 uctypes.addressof(src_data)
        # 這會有一點點開銷，但在 Python 層面是必須的
        f.write(src_data)
        
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed_mb:.2f} MB/s")

    # 3. Read Verify (using standard memoryview slice)
    print("\n--- [ViperRamFS] Read Speed Test ---")
    f.seek(0)
    read_buf = bytearray(chunk_size)
    
    t0 = time.ticks_ms()
    while True:
        n = f.readinto(read_buf)
        if n == 0: break
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Read {total_size/1024} KB in {diff} ms")
    print(f"Read Speed: {speed_mb:.2f} MB/s")

if __name__ == "__main__":
    run_test()

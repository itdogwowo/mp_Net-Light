# fast_ram_test.py
# 測試 FastRamFS 的極速效能
import uos
import time
import gc
import machine
from fast_ram_fs import FastRamFS

def run_test():
    print("=== System Info ===")
    print(f"Freq: {machine.freq() / 1000000} MHz")
    gc.collect()
    print(f"Free RAM: {gc.mem_free() / 1024} KB")
    
    # 1. 初始化 FastRamFS
    # 注意：這個 FS 是共用一塊大內存，適合臨時緩衝
    try:
        # 分配 1MB (如果有 PSRAM)，否則請改小
        fs = FastRamFS(size_kb=1024) 
    except Exception as e:
        print(f"Alloc failed: {e}")
        return

    mount_point = "/fastram"
    print(f"Mounting {mount_point}...")
    try:
        uos.mount(fs, mount_point)
    except Exception:
        try:
            uos.umount(mount_point)
            uos.mount(fs, mount_point)
        except:
            pass

    # 2. 寫入測試 (模擬 FileRx)
    print("\n--- FastRamFS Write Speed Test ---")
    test_file = f"{mount_point}/temp.bin"
    chunk_size = 4096 
    total_size = 256 * 1024 # 256KB
    data = b'\xAA' * chunk_size
    
    t0 = time.ticks_ms()
    # 使用標準 open() 接口
    with open(test_file, "wb") as f:
        for _ in range(total_size // chunk_size):
            f.write(data)
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Wrote {total_size/1024} KB in {diff} ms")
    print(f"Write Speed: {speed_mb:.2f} MB/s")  # 注意這裡是 MB/s

    # 3. 讀取測試 (模擬 校驗)
    print("\n--- FastRamFS Read Speed Test ---")
    t0 = time.ticks_ms()
    with open(test_file, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
            # 模擬校驗運算 (假設 hashlib 很快)
            pass
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Read {total_size/1024} KB in {diff} ms")
    print(f"Read Speed: {speed_mb:.2f} MB/s")

    # 4. 清理
    print("\n--- Cleanup ---")
    uos.umount(mount_point)
    print("Unmounted.")

if __name__ == "__main__":
    run_test()

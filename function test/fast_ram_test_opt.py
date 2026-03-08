# fast_ram_test_opt.py
# 測試 FastRamFS Opt 的極速效能 (對比 VFS vs Direct)
import uos
import time
import gc
import machine
from fast_ram_fs_opt import FastRamFSOpt

def run_test():
    print("=== System Info ===")
    print(f"Freq: {machine.freq() / 1000000} MHz")
    gc.collect()
    print(f"Free RAM: {gc.mem_free() / 1024} KB")
    
    # 1. 初始化 FastRamFS
    try:
        # 分配 1MB (如果有 PSRAM)，否則請改小
        fs = FastRamFSOpt(size_kb=1024) 
    except Exception as e:
        print(f"Alloc failed: {e}")
        return

    mount_point = "/fastram_opt"
    print(f"Mounting {mount_point}...")
    try:
        uos.mount(fs, mount_point)
    except Exception:
        try:
            uos.umount(mount_point)
            uos.mount(fs, mount_point)
        except:
            pass

    chunk_size = 4096 
    total_size = 256 * 1024 # 256KB
    data = b'\xAA' * chunk_size

    # 2. VFS 寫入測試 (標準 open)
    print("\n--- [VFS Mode] Write Speed Test ---")
    test_file = f"{mount_point}/temp.bin"
    
    t0 = time.ticks_ms()
    with open(test_file, "wb") as f:
        for _ in range(total_size // chunk_size):
            f.write(data)
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"VFS Wrote {total_size/1024} KB in {diff} ms")
    print(f"VFS Write Speed: {speed_mb:.2f} MB/s")

    # 3. Direct Method Call 測試 (繞過 uos.mount)
    print("\n--- [Direct Mode] Write Speed Test ---")
    # 直接從 FS 對象獲取 File 對象
    f_direct = fs.open("direct.bin", "w")
    
    t0 = time.ticks_ms()
    for _ in range(total_size // chunk_size):
        f_direct.write(data)
    f_direct.close()
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"Direct Wrote {total_size/1024} KB in {diff} ms")
    print(f"Direct Write Speed: {speed_mb:.2f} MB/s")
    
    # 4. Read Speed (VFS)
    print("\n--- [VFS Mode] Read Speed Test ---")
    t0 = time.ticks_ms()
    with open(test_file, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    speed_mb = (total_size / 1024 / 1024) / (diff / 1000)
    print(f"VFS Read {total_size/1024} KB in {diff} ms")
    print(f"VFS Read Speed: {speed_mb:.2f} MB/s")

    # Cleanup
    try:
        uos.umount(mount_point)
    except:
        pass

if __name__ == "__main__":
    run_test()

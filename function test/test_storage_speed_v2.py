# test_storage_speed_v2.py
"""
MicroPython Storage & RAM Benchmark V2
1. 測試 Flash/SD 卡 極限寫入速度 (使用大緩衝)
2. 測試 PSRAM 讀寫速度
3. 測試 SHA256 在 RAM 中的運算速度 vs Flash 流式讀取
"""
import time
import os
import micropython
import machine
import gc
import hashlib

# 提升頻率
try:
    machine.freq(240000000)
except:
    pass

def get_free_mem():
    gc.collect()
    return gc.mem_free()

@micropython.native
def test_write_speed(filename, size_mb, chunk_size_kb=64):
    print(f"\n📝 Storage Write Test: {filename}")
    print(f"   Size: {size_mb} MB | Chunk: {chunk_size_kb} KB")
    
    # 準備大塊數據
    chunk_size = chunk_size_kb * 1024
    chunk = bytearray(chunk_size) 
    
    # 填入一些數據防止文件系統壓縮優化
    chunk[0] = 0xAA
    chunk[-1] = 0x55
    
    total_bytes = 0
    start = time.ticks_ms()
    
    try:
        with open(filename, "wb") as f:
            loops = (size_mb * 1024) // chunk_size_kb
            for _ in range(loops):
                n = f.write(chunk)
                total_bytes += n
        
        # 強制同步
        os.sync()
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    end = time.ticks_ms()
    elapsed = time.ticks_diff(end, start) / 1000
    speed_mb = (total_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0
    
    print(f"⏱️ Time:  {elapsed:.3f} s")
    print(f"⚡ Speed: {speed_mb:.3f} MB/s ({speed_mb*1024:.1f} KB/s)")
    
    # 清理
    try:
        os.remove(filename)
    except:
        pass

@micropython.native
def test_sha256_ram(size_mb):
    print(f"\n🚀 SHA256 RAM Benchmark (Size: {size_mb} MB)")
    
    # 嘗試分配大內存 (模擬 PSRAM)
    try:
        size_bytes = size_mb * 1024 * 1024
        buf = bytearray(size_bytes)
        print(f"✅ Allocated {size_mb} MB in RAM")
    except MemoryError:
        print(f"❌ Failed to allocate {size_mb} MB. Using 1 MB chunk instead.")
        size_bytes = 1024 * 1024
        buf = bytearray(size_bytes)
    
    h = hashlib.sha256()
    
    start = time.ticks_ms()
    
    # 計算 SHA256
    # 如果是完整的大 buffer，直接 update
    # 為了模擬大文件，如果是小 buffer 則循環 update
    if len(buf) < size_mb * 1024 * 1024:
        loops = (size_mb * 1024 * 1024) // len(buf)
        for _ in range(loops):
            h.update(buf)
    else:
        h.update(buf)
        
    end = time.ticks_ms()
    elapsed = time.ticks_diff(end, start) / 1000
    speed_mb = size_mb / elapsed if elapsed > 0 else 0
    
    print(f"⏱️ Time:  {elapsed:.3f} s")
    print(f"⚡ Speed: {speed_mb:.3f} MB/s")

def mount_sd():
    # 嘗試掛載 SD 卡 (根據用戶提供的引腳)
    try:
        # 如果已經掛載，先卸載
        try:
            from esp32 import LDO
            # 注意：這裡使用硬編碼的 LDO 參數，可能需要根據實際情況調整
            ldo = LDO(4, 3300, adjustable=True)
            
            os.umount('/sd')
        except: pass
            
        from machine import Pin, SDCard
        # 用戶提供的引腳配置
        sd = SDCard(slot=1, width=4, 
                    clk=43, cmd=44, 
                    data=(39, 40, 41, 42), 
                    freq=40_000_000)
        os.mount(sd, '/sd')
        print("✅ SD Card Mounted at /sd")
        return True
    except Exception as e:
        print(f"⚠️ SD Mount Failed: {e}")
        return False

if __name__ == "__main__":
    print("-" * 50)
    print(f"System Freq: {machine.freq() / 1000000} MHz")
    print(f"Free RAM: {get_free_mem() // 1024} KB")
    print("-" * 50)

    # 1. 測試 SHA256 (RAM)
    test_sha256_ram(10) # 10MB 測試 (如果 RAM 夠大)
    
    # 2. 測試 Flash 寫入
    print("\n--- Internal Flash Test ---")
    test_write_speed("bench_flash.bin", 2)

    
    # 3. 測試 SD 寫入
    if mount_sd():
        print("\n--- SD Card Test ---")
        test_write_speed("/sd/bench_sd.bin", 10) # 10MB 測試

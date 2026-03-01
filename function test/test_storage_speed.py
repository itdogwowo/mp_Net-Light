# test_storage_speed.py
"""
MicroPython Storage Benchmark (Write/Read)
測試 SD 卡或 Flash 的寫入速度
"""
import time
import os
import micropython
import machine

try:
    machine.freq(240000000)
except:
    pass

@micropython.native
def test_write_speed(filename, size_mb):
    print(f"\n📝 Storage Write Test: {filename}")
    
    # 1. 準備大塊數據
    chunk_size = 64 * 1024 # 64KB
    chunk = bytearray(chunk_size) # 全 0
    
    total_bytes = 0
    start = time.ticks_ms()
    
    try:
        with open(filename, "wb") as f:
            for _ in range(size_mb * 16): # 64KB * 16 = 1MB
                n = f.write(chunk)
                total_bytes += n
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    end = time.ticks_ms()
    elapsed = time.ticks_diff(end, start) / 1000
    speed_mb = (total_bytes / 1024 / 1024) / elapsed
    
    print(f"⏱️ Time:  {elapsed:.3f} s")
    print(f"⚡ Speed: {speed_mb:.2f} MB/s")
    return speed_mb

if __name__ == "__main__":
    test_file = "/sd/bench_10mb.bin"
    try:
        os.stat("/sd")
        print("💾 Testing on SD Card")
    except:
        print("💾 Testing on Flash (LittleFS)")
        test_file = "bench_10mb.bin"
    
    test_write_speed(test_file, 10) # 10MB

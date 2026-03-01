# test_sha256_speed.py
"""
MicroPython SHA256 Benchmark
測試在 ESP32 上計算文件摘要的極限速度
"""
import hashlib
import time
import os
import micropython
import machine

# 提升頻率
try:
    machine.freq(240000000)
except:
    pass

def create_dummy_file(filename, size_mb):
    print(f"📄 Creating {size_mb}MB dummy file...")
    with open(filename, "wb") as f:
        chunk = os.urandom(64 * 1024)
        for _ in range(size_mb * 16): # 64KB * 16 = 1MB
            f.write(chunk)
    print("✅ Created")

@micropython.native
def benchmark_sha256(filename):
    print(f"\n🚀 SHA256 Benchmark: {filename}")
    
    # 1. 初始化
    h = hashlib.sha256()
    buf = bytearray(32 * 1024) # 32KB 緩衝區
    mv = memoryview(buf)
    
    total_bytes = 0
    start = time.ticks_ms()
    
    try:
        with open(filename, "rb") as f:
            while True:
                # 2. 讀取塊
                n = f.readinto(mv)
                if not n: break
                
                # 3. 更新摘要 (核心耗時)
                # update() 通常是 C 實現，速度很快
                # 如果 n < len(mv)，需要切片
                if n < len(mv):
                    h.update(mv[:n])
                else:
                    h.update(mv)
                
                total_bytes += n
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    end = time.ticks_ms()
    elapsed = time.ticks_diff(end, start) / 1000
    speed_mb = (total_bytes / 1024 / 1024) / elapsed
    
    digest = h.digest()
    
    print("-" * 40)
    print(f"⏱️ Time:  {elapsed:.3f} s")
    print(f"⚡ Speed: {speed_mb:.2f} MB/s")
    print(f"🔑 Digest: {digest.hex()[:16]}...")
    print("-" * 40)
    return speed_mb

if __name__ == "__main__":
    test_file = "/sd/test_10mb.bin"
    # 嘗試在 SD 卡上測試 (如果有的話)
    try:
        os.stat("/sd")
        print("💾 Testing on SD Card")
    except:
        print("💾 Testing on Flash (LittleFS)")
        test_file = "test_10mb.bin"
    
    # 創建測試文件
    try:
        os.stat(test_file)
    except:
        create_dummy_file(test_file, 10) # 10MB
        
    benchmark_sha256(test_file)

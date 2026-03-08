# fast_ram_test_v5.py
# 測試 v5: Viper Emitter vs Slice Assignment
import time
import gc
import machine
import micropython

# Viper copy function
# Takes pointers to buffers and length
@micropython.viper
def viper_memcpy(dest_ptr: ptr8, src_ptr: ptr8, count: int):
    for i in range(count):
        dest_ptr[i] = src_ptr[i]

@micropython.viper
def viper_write_offset(dest_ptr: ptr8, offset: int, src_ptr: ptr8, count: int):
    for i in range(count):
        dest_ptr[offset + i] = src_ptr[i]

def run_test():
    print("=== System Info ===")
    print(f"Freq: {machine.freq() / 1000000} MHz")
    gc.collect()
    print(f"Free RAM: {gc.mem_free() / 1024} KB")
    
    # Alloc buffers
    chunk_size = 4096 
    total_size = 256 * 1024 # 256KB
    
    # Large destination buffer (simulating RAM Disk)
    print("Allocating 1MB buffer...")
    try:
        dest_buf = bytearray(1024 * 1024)
        dest_mv = memoryview(dest_buf)
    except MemoryError:
        print("Not enough RAM!")
        return

    # Source data
    src_data = b'\xAA' * chunk_size
    src_mv = memoryview(src_data)

    print(f"Test size: {total_size/1024} KB")
    loops = total_size // chunk_size

    # 1. Standard Slice Assignment (Baseline)
    print("\n--- [Slice Assignment] ---")
    pos = 0
    t0 = time.ticks_ms()
    for _ in range(loops):
        # This is what v3 did
        dest_mv[pos : pos + chunk_size] = src_mv
        pos += chunk_size
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    print(f"Time: {diff} ms")
    print(f"Speed: {(total_size/1024/1024)/(diff/1000):.2f} MB/s")

    # 2. Viper Pointer Copy
    print("\n--- [Viper Pointer Copy] ---")
    pos = 0
    
    # Get pointers (requires casting to int then ptr8 in viper call usually, 
    # but let's see if we can pass memoryview directly to viper args typed as ptr8? 
    # No, usually need uctypes.addressof or similar. 
    # Viper can take object and cast?
    # Let's use memoryview simply)
    
    # Actually, getting address of bytearray content in pure python is tricky without uctypes
    import uctypes
    dest_addr = uctypes.addressof(dest_buf)
    src_addr = uctypes.addressof(src_data)
    
    t0 = time.ticks_ms()
    for _ in range(loops):
        # Call viper function
        viper_write_offset(dest_addr, pos, src_addr, chunk_size)
        pos += chunk_size
    t1 = time.ticks_ms()
    
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    print(f"Time: {diff} ms")
    print(f"Speed: {(total_size/1024/1024)/(diff/1000):.2f} MB/s")

    # 3. Viper Copy (No offset, just to see loop speed)
    print("\n--- [Viper Loop Speed (Small)] ---")
    t0 = time.ticks_ms()
    for _ in range(loops):
        viper_memcpy(dest_addr, src_addr, chunk_size)
    t1 = time.ticks_ms()
    diff = time.ticks_diff(t1, t0)
    if diff == 0: diff = 1
    print(f"Time: {diff} ms")
    print(f"Speed: {(total_size/1024/1024)/(diff/1000):.2f} MB/s")

if __name__ == "__main__":
    run_test()

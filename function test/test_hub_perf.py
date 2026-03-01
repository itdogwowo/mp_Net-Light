
import time
import _thread
import sys
import random

# 假設 lib 在路徑中，或直接從 lib.buffer_hub 導入
# 根據 main.py 的寫法: from lib.buffer_hub import AtomicStreamHub
try:
    from lib.buffer_hub import AtomicStreamHub
except ImportError:
    # 為了方便測試時如果不在根目錄，嘗試添加路徑 (僅保留基本的路徑修正)
    sys.path.append('slave')
    from lib.buffer_hub import AtomicStreamHub

# Configuration
BUF_SIZE = 1024 * 10  # 10KB per frame
NUM_BUFFERS = 3
TEST_DURATION = 3.0   # Seconds

# Shared stats (simple dict for mutable state across threads)
stats = {
    "tx_count": 0,
    "rx_count": 0,
    "tx_reject": 0,
    "running": True
}

def producer_task(hub_inst):
    """
    Simulate Data Source (e.g., Network or SD Card)
    Tries to write as fast as possible.
    """
    print("[Core 0] Producer started.")
    counter = 0
    
    while stats["running"]:
        # Try to get a buffer
        view = hub_inst.get_write_view()
        if view is None:
            stats["tx_reject"] += 1
            # Busy wait or yield? In real life, network waits. 
            # Here we just spin or small sleep to simulate backpressure
            time.sleep(0.00001) 
            continue
            
        # Simulate filling data (e.g. socket read)
        # We'll just write a sequence number to the first byte to verify
        # To simulate cost of filling, maybe we don't do full memset, 
        # but in MicroPython readinto is C-level fast.
        # Let's just set the first byte.
        try:
            view[0] = counter % 255
            view[-1] = 0xAA # Marker
        except Exception:
            pass # buffer size might be small? 10KB is enough.
        
        # Commit
        hub_inst.commit()
        stats["tx_count"] += 1
        counter += 1
        
    print("[Core 0] Producer stopped.")

def consumer_task(hub_inst):
    """
    Simulate Data Consumer (e.g., LED Strip Engine)
    Reads and 'displays' as fast as possible.
    """
    print("[Core 1] Consumer started.")
    
    last_seq = -1
    
    while stats["running"]:
        # Try to read
        view = hub_inst.get_read_view()
        if view is None:
            # No data waiting
            # time.sleep(0.00001)
            continue
            
        # Simulate processing (LED shifting)
        # Verify data integrity
        try:
            seq = view[0]
            marker = view[-1]
            
            if marker != 0xAA:
                print(f"❌ Corruption detected! Marker: {marker}")
        except Exception:
            pass

        # Verify sequence continuity (if applicable)
        if last_seq != -1:
            diff = (seq - last_seq) % 255
            # diff 1 is normal
            # diff 0 means we read the same frame? Should not happen with locking.
            if diff != 1:
                 # print(f"⚠️ Gap: {last_seq} -> {seq}")
                 pass
                
        last_seq = seq
        stats["rx_count"] += 1
        
    print("[Core 1] Consumer stopped.")

def run_test():
    print(f"🔥 Starting Performance Test (Size: {BUF_SIZE} bytes, Buffers: {NUM_BUFFERS})")
    
    hub = AtomicStreamHub(BUF_SIZE, NUM_BUFFERS)
    
    # Start Consumer thread
    _thread.start_new_thread(consumer_task, (hub,))
    
    # Start Producer in a thread too
    _thread.start_new_thread(producer_task, (hub,))
    
    # Monitor
    start_time = time.time()
    while time.time() - start_time < TEST_DURATION:
        time.sleep(1)
        # print(f"Status: Tx={stats['tx_count']}, Rx={stats['rx_count']}, Rejects={stats['tx_reject']}")
        
    stats["running"] = False
    time.sleep(0.5) # Let threads finish
    
    duration = time.time() - start_time
    # Avoid div by zero
    if duration <= 0: duration = 0.001

    total_mb = (stats['rx_count'] * BUF_SIZE) / (1024 * 1024)
    throughput = total_mb / duration
    fps = stats['rx_count'] / duration
    
    print("\n════════════════════════════════════════")
    print(f"✅ Test Complete ({duration:.2f}s)")
    print(f"📊 Total Frames Processed: {stats['rx_count']}")
    print(f"🚀 Throughput: {throughput:.2f} MB/s")
    print(f"🎞️  FPS (Simulated): {fps:.2f} fps")
    print(f"⚠️  Producer Rejects (Full): {stats['tx_reject']}")
    print("════════════════════════════════════════")

if __name__ == "__main__":
    run_test()

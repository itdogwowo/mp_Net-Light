
import sys

# 假設 lib 在路徑中，或直接從 lib.buffer_hub 導入
try:
    from lib.buffer_hub import AtomicStreamHub
except ImportError:
    # 為了方便測試時如果不在根目錄，嘗試添加路徑
    sys.path.append('slave')
    from lib.buffer_hub import AtomicStreamHub

def test_hub():
    print("Testing AtomicStreamHub...")
    hub = AtomicStreamHub(size=5, num_buffers=3)
    
    # 1. Test basic write/read
    assert hub.write_from(b'11111') == True
    assert hub.write_from(b'22222') == True
    assert hub.write_from(b'33333') == True
    print(f"Fill level after 3 writes: {hub.get_fill_level()}") # Should be 3
    
    # 2. Test overflow
    assert hub.write_from(b'44444') == False
    print("Overflow check OK")
    
    # 3. Test read_into
    buf = bytearray(5)
    assert hub.read_into(buf) == True
    print(f"Read: {buf}")
    assert buf == b'11111'
    print("Read check OK")
    
    # 4. Test write after read
    assert hub.write_from(b'44444') == True
    print("Write after read OK")
    
    # 5. Test get_read_view locking logic
    # Current buffer state:
    # Slot 0: IDLE (was 11111, read)
    # Slot 1: READY (22222)
    # Slot 2: READY (33333)
    # Slot 0: READY (44444) (written just now)
    
    # Next read should be 22222
    view1 = hub.get_read_view()
    print(f"View 1: {bytes(view1)}")
    assert bytes(view1) == b'22222'
    
    # Next read should be 33333
    view2 = hub.get_read_view()
    print(f"View 2: {bytes(view2)}")
    assert bytes(view2) == b'33333'
    
    # Next read should be 44444
    view3 = hub.get_read_view()
    print(f"View 3: {bytes(view3)}")
    assert bytes(view3) == b'44444'
    
    # Next read should be None
    view4 = hub.get_read_view()
    print(f"View 4: {view4}")
    assert view4 is None
    
    print("Locking logic OK")
    
    # 6. Test Flush
    hub.write_from(b'AAAAA')
    hub.flush()
    assert hub.get_fill_level() == 0
    assert hub.get_read_view() is None
    print("Flush OK")

if __name__ == "__main__":
    test_hub()

# test_network_rx.py (MicroPython 兼容版)
"""
純網絡接收測試 - MicroPython 版本
測試 PC → MCU 的真實帶寬
"""

import socket
import time

# test_network_rx.py (MicroPython 完全兼容版)
"""
純網絡接收測試 - MicroPython 精簡版
"""

import socket
import time

def test_network_receive():
    """純接收測試"""
    lan = bus.get_service("lan")
    
    ip_info = lan.ipconfig("addr4")
    print(ip_info)
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', 8888))
    s.listen(1)
    
    print("=" * 50)
    print("🚀 Network RX Test")
    print("   Port: 8888")
    print("=" * 50)
    
    conn, addr = s.accept()
    print(f"\n✅ Connected: {addr}")
    
    # WebSocket 握手
    conn.recv(1024)
    conn.send(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
    
    conn.setblocking(False)
    
    print("\n🔥 Receiving...")
    print("-" * 50)
    
    total = 0
    packets = 0
    start = time.ticks_ms()
    last = start
    
    try:
        while True:
            try:
                # 🔥 使用 recv() 而不是 recv_into()
                data = conn.recv(8192)
                
                if data:
                    n = len(data)
                    total += n
                    packets += 1
                    
                    now = time.ticks_ms()
                    if time.ticks_diff(now, last) > 1000:
                        elapsed = time.ticks_diff(now, start) / 1000
                        speed = (total / 1024) / elapsed if elapsed > 0 else 0
                        
                        print(f"📊 {total//1024:6} KB | {speed:6.1f} KB/s | {packets:5} pkts")
                        last = now
                
                else:
                    # 對端關閉
                    time.sleep_ms(1)
                time.sleep_ms(1)
            
            except OSError:
                # EAGAIN / EWOULDBLOCK
                time.sleep_ms(1)
    
    except KeyboardInterrupt:
        print("\n\n👋 Stopped")
    
    finally:
        elapsed = time.ticks_diff(time.ticks_ms(), start) / 1000
        speed = (total / 1024) / elapsed if elapsed > 0 else 0
        
        print("-" * 50)
        print(f"✅ Complete")
        print(f"   Total: {total // 1024} KB")
        print(f"   Time: {elapsed:.1f}s")
        print(f"   Speed: {speed:.1f} KB/s")
        print(f"   Packets: {packets}")
        print("=" * 50)
        
        conn.close()
        s.close()

# 執行
test_network_receive()


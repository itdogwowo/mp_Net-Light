# test_network_rx_extreme_v2.py
"""
MicroPython Network RX Test - Compatibility Version
適配無 recv_into 的環境，同時優化性能。
"""
import socket
import time
import micropython
import machine
import gc
from lib.sys_bus import bus

# 嘗試提升 CPU 頻率到 240MHz
# try:
#     machine.freq(240000000)
# except:
#     pass

def get_lan_ip():
    """從 bus 獲取 LAN IP"""
    print("-" * 40)
    try:
        lan = bus.get_service("lan")
        if lan:
            # 根據用戶提供的代碼獲取 IP
            ip_info = lan.ipconfig("addr4")
            print(f"🌐 LAN Info: {ip_info}")
            if ip_info and len(ip_info) > 0:
                return ip_info[0]
    except Exception as e:
        print(f"⚠️ 無法獲取 LAN 服務或 IP: {e}")
    
    print("⚠️ 未檢測到有效 IP，將監聽 0.0.0.0")
    return "0.0.0.0"

@micropython.native
def test_receive():
    # 1. 獲取並顯示 IP
    my_ip = get_lan_ip()
    port = 8888
    
    # 2. 建立 Socket
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', port))
    s.listen(1)
    
    print(f"\n🚀 Server listening on {my_ip}:{port}")
    print("⏳ Waiting for connection...")
    
    conn, addr = s.accept()
    print(f"✅ Connected: {addr}")
    
    # 3. 檢測可用方法
    # 優先級: readinto (最快, 0 alloc) > recv (兼容, alloc)
    use_readinto = False
    if hasattr(conn, 'readinto'):
        use_readinto = True
        print("🔧 Using: readinto() (Zero-Copy Mode)")
    else:
        print("🔧 Using: recv() (Compatibility Mode)")
        
    # 預分配緩衝區 (僅對 readinto 有效)
    buf = bytearray(32 * 1024)
    
    total_bytes = 0
    start = time.ticks_ms()
    last_print = start
    
    print("\n🔥 Receiving data...")
    
    try:
        while True:
            try:
                if use_readinto:
                    # 零拷貝接收
                    n = conn.readinto(buf)
                    if not n: 
                        break # 連接關閉
                else:
                    # 兼容模式接收 (會分配內存)
                    data = conn.recv(16384)
                    if not data: 
                        break # 連接關閉
                    n = len(data)
                
                total_bytes += n
                
                # 統計
                now = time.ticks_ms()
                if time.ticks_diff(now, last_print) > 1000:
                    elapsed = time.ticks_diff(now, start) / 1000
                    speed_mb = (total_bytes / 1024 / 1024) / elapsed
                    print(f"⚡ Speed: {speed_mb:5.2f} MB/s | Total: {total_bytes//1024//1024} MB")
                    last_print = now
                    
            except OSError:
                break
                
    except Exception as e:
        print(f"\n❌ Error: {e}")
        
    finally:
        end = time.ticks_ms()
        elapsed = time.ticks_diff(end, start) / 1000
        speed_mb = (total_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0
        
        print("\n" + "=" * 40)
        print(f"🏁 Test Complete")
        print(f"   Total: {total_bytes / 1024 / 1024:.2f} MB")
        print(f"   Time:  {elapsed:.2f} s")
        print(f"   Speed: {speed_mb:.2f} MB/s")
        print("=" * 40)
        
        conn.close()
        s.close()

if __name__ == "__main__":
    test_receive()

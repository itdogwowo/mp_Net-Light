# slave/test_rx_server.py
import socket
import time
import network
import gc
from machine import Pin

def test_server(port=8888):
    # 1. 確保網絡已連接
#     wlan = network.WLAN(network.STA_IF)
    lan = None
    try:
        lan = network.LAN(mdc=Pin(31), mdio=Pin(52), power=None, phy_addr=1, phy_type=network.PHY_IP101)
    except: pass

    ip = None
    ip = lan.ifconfig()[0]
#     if wlan.active() and wlan.isconnected():
#         ip = wlan.ifconfig()[0]
#     elif lan and lan.active() and lan.isconnected():
#         ip = lan.ifconfig()[0]
    
    if not ip:
        print("❌ 網絡未連接")
        return

    print(f"🚀 啟動接收測試服務 @ {ip}:{port}")
    
    # 2. 創建監聽 Socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', port))
    s.listen(1)
    
    print("⏳ 等待 PC 連接...")
    conn, addr = s.accept()
    print(f"✅ 連接來自: {addr}")
    
    # 3. 握手 (假裝是 WebSocket Server)
    # 接收 Client 的 GET ...
    req = conn.recv(1024)
    if b"Upgrade: websocket" in req:
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
        )
        conn.send(resp.encode())
        print("✅ WebSocket 握手完成")
    
    # 4. 高速接收循環
    print("🔥 開始接收數據...")
    
    total_bytes = 0
    start_time = time.ticks_ms()
    last_print = start_time
    
    # 預分配緩衝區 (64KB)
    try:
        buf = bytearray(64 * 1024) 
    except:
        buf = bytearray(16 * 1024)
    
    view = memoryview(buf)
    
    # 檢測可用方法
    use_recv_into = hasattr(conn, 'recv_into')
    use_readinto = hasattr(conn, 'readinto')
    
    print(f"ℹ️ 使用接收方法: {'recv_into' if use_recv_into else ('readinto' if use_readinto else 'recv')}")

    try:
        while True:
            # 盡可能多讀
            if use_recv_into:
                n = conn.recv_into(view)
            elif use_readinto:
                n = conn.readinto(view)
            else:
                data = conn.recv(len(view))
                if not data: 
                    n = 0
                else:
                    n = len(data)
                    # 這裡不需要拷貝，因為我們只是測試接收速度，丟棄數據即可
                    # view[:n] = data 
            
            if not n: break
            
            total_bytes += n
            
            # 每秒打印一次狀態
            now = time.ticks_ms()
            if time.ticks_diff(now, last_print) > 1000:
                elapsed = time.ticks_diff(now, start_time) / 1000
                speed = (total_bytes / 1024) / elapsed
                print(f"📊 已接收: {total_bytes/1024:.0f} KB | 速度: {speed:.1f} KB/s")
                last_print = now
                
    except Exception as e:
        print(f"❌ 接收錯誤: {e}")
    finally:
        end_time = time.ticks_ms()
        elapsed = time.ticks_diff(end_time, start_time) / 1000
        speed = (total_bytes / 1024) / elapsed if elapsed > 0 else 0
        
        print("-" * 40)
        print(f"🏁 測試結束")
        print(f"📦 總量: {total_bytes/1024:.1f} KB")
        print(f"⏱️ 耗時: {elapsed:.2f} s")
        print(f"🚀 平均速度: {speed:.2f} KB/s")
        print("-" * 40)
        
        conn.close()
        s.close()

if __name__ == "__main__":
    test_server()

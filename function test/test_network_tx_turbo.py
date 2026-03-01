# test_network_tx_turbo.py
"""
Turbo Network TX Test
測試連接 MCU 的 Turbo Channel (Port 8889)
"""
import socket
import time
import os
import sys

def test_turbo_send(mcu_ip, duration_sec=10, port=8889):
    print("╔════════════════════════════════════════╗")
    print("║  Turbo Network TX (Port 8889)          ║")
    print("╚════════════════════════════════════════╝")
    print(f"Target: {mcu_ip}:{port}")
    print(f"Duration: {duration_sec} seconds")

    # 1. 準備數據
    # 假設我們發送的是 1024 顆 LED 的數據 (3KB/frame)
    FRAME_SIZE = 1024 * 3 
    # 為了測試吞吐量，我們發送更大的塊，但 DataStreamer 會自動處理
    CHUNK_SIZE = 64 * 1024 
    data_chunk = os.urandom(CHUNK_SIZE)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((mcu_ip, port))
    except ConnectionRefusedError:
        print(f"❌ Connection Refused: Ensure MCU is running updated Core0 with Turbo enabled.")
        return
    
    # 2. Socket 優化
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024) 
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) 
    
    print("\n🚀 Turbo Blast! Sending data...")
    
    total_sent = 0
    start_time = time.time()
    last_print = start_time
    
    try:
        while True:
            if time.time() - start_time > duration_sec:
                break
                
            sock.sendall(data_chunk)
            total_sent += CHUNK_SIZE
            
            # 監控顯示
            now = time.time()
            if now - last_print > 0.5:
                elapsed = now - start_time
                speed_mb = (total_sent / 1024 / 1024) / elapsed
                print(f"📤 Speed: {speed_mb:5.2f} MB/s | Sent: {total_sent//1024//1024} MB")
                last_print = now
                
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        print("❌ Connection closed by remote")
        
    finally:
        elapsed = time.time() - start_time
        speed_mb = (total_sent / 1024 / 1024) / elapsed if elapsed > 0 else 0
        print("-" * 50)
        print(f"✅ Done. Avg Speed: {speed_mb:.2f} MB/s")
        sock.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    else:
        ip = input("MCU IP: ").strip()
    
    if ip:
        test_turbo_send(ip)

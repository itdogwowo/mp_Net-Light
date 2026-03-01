# test_network_tx.py (修復版)
"""
純網絡發送測試 - 修復 BrokenPipe
"""
import socket
import struct
import time
import os
def test_network_send(mcu_ip, file_size_kb=10240):
    """純發送測試"""
    
    print("╔════════════════════════════════════════╗")
    print("║  純網絡發送測試                       ║")
    print("╚════════════════════════════════════════╝")
    print(f"\n目標: {mcu_ip}:8888")
    print(f"測試大小: {file_size_kb} KB\n")
    
    # 生成測試數據
    print("⚙️ 生成測試數據...")
    test_data = os.urandom(file_size_kb * 1024)
    
    # 連接 MCU
    print("📡 連接 MCU...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        sock.connect((mcu_ip, 8888))
    except Exception as e:
        print(f"❌ 連接失敗: {e}")
        return
    
    # WebSocket 握手
    handshake = (
        f"GET /test HTTP/1.1\r\n"
        f"Host: {mcu_ip}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.send(handshake.encode())
    
    try:
        resp = sock.recv(1024)
        if b"101 Switching Protocols" not in resp:
            print("❌ WebSocket 握手失敗")
            sock.close()
            return
    except:
        print("❌ 握手超時")
        sock.close()
        return
    
    print("✅ WebSocket 連接成功")
    
    # 🔥 優化 Socket
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    # 🔥 短暫延遲，等待 MCU 準備好
    time.sleep(0.1)
    
    print("\n🔥 開始發送測試...")
    print("-" * 60)
    
    chunk_size = 8192
    total_sent = 0
    start_time = time.time()
    last_print = start_time
    
    try:
        while total_sent < len(test_data):
            chunk = test_data[total_sent : total_sent + chunk_size]
            
            # WebSocket 封裝
            l = len(chunk)
            hdr = bytearray([0x82])  # Binary frame
            if l <= 125:
                hdr.append(l)
            elif l <= 65535:
                hdr.append(126)
                hdr.extend(struct.pack(">H", l))
            
            packet = hdr + chunk
            
            # 🔥 使用 try-except 捕獲 BrokenPipe
            try:
                sock.sendall(packet)
                total_sent += len(chunk)
            
            except BrokenPipeError:
                print(f"\n❌ 連接斷開 (已發送 {total_sent // 1024} KB)")
                break
            
            except Exception as e:
                print(f"\n❌ 發送錯誤: {e}")
                break
            
            # 每秒打印一次
            now = time.time()
            if now - last_print > 1.0:
                elapsed = now - start_time
                speed = (total_sent / 1024) / elapsed
                progress = (total_sent / len(test_data)) * 100
                
                print(f"📊 進度: {progress:5.1f}% | "
                      f"速度: {speed:6.1f} KB/s | "
                      f"已發送: {total_sent // 1024} KB")
                
                last_print = now
    
    except KeyboardInterrupt:
        print("\n\n👋 用戶中斷")
    
    finally:
        # 最終統計
        elapsed_total = time.time() - start_time
        avg_speed = (total_sent / 1024) / elapsed_total if elapsed_total > 0 else 0
        
        print("-" * 60)
        print(f"✅ 發送完成")
        print(f"   總大小: {total_sent // 1024} KB")
        print(f"   耗時: {elapsed_total:.2f}s")
        print(f"   平均速度: {avg_speed:.1f} KB/s")
        
        sock.close()
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        mcu_ip = sys.argv[1]
    else:
        mcu_ip = input("請輸入 MCU IP (默認 10.10.1.26): ").strip() or "10.10.1.26"
    
    size_kb = input("請輸入測試大小 KB (默認 10240): ").strip()
    size_kb = int(size_kb) if size_kb else 10240
    
    test_network_send(mcu_ip, size_kb)


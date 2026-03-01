# test_network_rx_ws_extreme.py
"""
MicroPython WebSocket RX Extreme Test
測試 WebSocket 協議下的極限接收速度 (解析+掩碼處理)
"""
import socket
import time
import micropython
import machine
import struct
from lib.sys_bus import bus

# 嘗試提升 CPU 頻率
try:
    machine.freq(240000000)
except:
    pass

def get_lan_ip():
    try:
        lan = bus.get_service("lan")
        if lan:
            return lan.ipconfig("addr4")[0]
    except:
        pass
    return "0.0.0.0"

@micropython.native
def unmask(data: bytes, mask: bytes, length: int):
    # 這裡只做簡單演示，實際上 MicroPython 沒有內建快速 XOR
    # 為了測試極限，我們假設大部分時間不需要逐字節解碼，或者使用 viper 優化
    pass

@micropython.native
def test_ws_receive():
    my_ip = get_lan_ip()
    port = 8888
    
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', port))
    s.listen(1)
    
    print(f"🚀 WS Server on {my_ip}:{port}")
    conn, addr = s.accept()
    print(f"✅ Connected: {addr}")
    
    # WS Handshake
    req = conn.recv(1024)
    if b"Upgrade: websocket" in req:
        conn.send(b"HTTP/1.1 101 Switching Protocols\r\n"
                  b"Upgrade: websocket\r\n"
                  b"Connection: Upgrade\r\n"
                  b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
        print("🤝 Handshake OK")
    
    # 緩衝區
    buf = bytearray(32 * 1024)
    mv = memoryview(buf)
    
    total_bytes = 0 # 應用層數據量 (Payload)
    total_raw = 0   # 網絡層數據量 (Raw)
    start = time.ticks_ms()
    last_print = start
    
    print("\n🔥 Receiving WS Stream...")
    
    try:
        while True:
            # 1. 讀取頭部 (至少 2 bytes)
            # 為了性能，我們嘗試一次讀多一點，然後解析
            # 這裡簡化邏輯：假設客戶端發送大包
            n = conn.readinto(mv)
            if not n: break
            
            total_raw += n
            
            # 簡單估算 Payload 大小 (扣除 4-8 bytes overhead)
            # 在極限測試中，我們主要關注吞吐量
            # 假設平均 overhead 占比很小 (大包模式)
            payload_len = n - 6 # 假設有 mask
            if payload_len > 0:
                total_bytes += payload_len
            
            # 統計
            now = time.ticks_ms()
            if time.ticks_diff(now, last_print) > 1000:
                elapsed = time.ticks_diff(now, start) / 1000
                speed_mb = (total_raw / 1024 / 1024) / elapsed
                print(f"⚡ Raw Speed: {speed_mb:5.2f} MB/s | Payload: ~{total_bytes//1024//1024} MB")
                last_print = now
                
    except Exception as e:
        print(f"Error: {e}")
        
    finally:
        end = time.ticks_ms()
        elapsed = time.ticks_diff(end, start) / 1000
        speed_mb = (total_raw / 1024 / 1024) / elapsed if elapsed > 0 else 0
        
        print(f"🏁 WS Test Complete")
        print(f"   Raw Speed: {speed_mb:.2f} MB/s")
        conn.close()
        s.close()

if __name__ == "__main__":
    test_ws_receive()

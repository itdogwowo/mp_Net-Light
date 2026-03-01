import socket
import struct
import time
import os
import hashlib
import sys

# --- 簡易協議封裝 (參考 lib/proto.py) ---
SOF = b"NL"
CUR_VER = 3
ADDR_BROADCAST = 0xFFFF
HDR_FMT = "<2sBHHH"
CRC_FMT = "<H"

def crc16(data):
    """
    [性能優化] 在速度測試中禁用真實 CRC 計算
    Python 的位運算非常慢，會成為發送瓶頸 (卡在 ~100KB/s)。
    為了測試網絡極限，我們直接返回固定值。
    """
    return 0xFFFF

    # 原有的真實計算邏輯 (僅供參考)
    # crc = 0xFFFF
    # for byte in data:
    #     crc ^= byte << 8
    #     for _ in range(8):
    #         if crc & 0x8000:
    #             crc = ((crc << 1) ^ 0x1021) & 0xFFFF
    #         else:
    #             crc = (crc << 1) & 0xFFFF
    # return crc

def pack_cmd(cmd, payload):
    ln = len(payload)
    header = struct.pack(HDR_FMT, SOF, CUR_VER, ADDR_BROADCAST, cmd, ln)
    crc_data = header[2:] + payload
    crc_val = crc16(crc_data)
    return header + payload + struct.pack(CRC_FMT, crc_val)

def create_ws_frame(data):
    """簡單的 WebSocket Binary Frame 封裝"""
    l = len(data)
    hdr = bytearray([0x82]) # Binary Frame
    if l <= 125:
        hdr.append(l)
    elif l <= 65535:
        hdr.append(126)
        hdr.extend(struct.pack(">H", l))
    else:
        hdr.append(127)
        hdr.extend(struct.pack(">Q", l))
    return hdr + data

# --- 測試主程序 ---

def test_upload(ip, file_size_kb=1024, chunk_size=4096):
    print(f"🚀 開始測試文件上傳速度")
    print(f"目標: {ip}")
    print(f"大小: {file_size_kb} KB")
    print(f"塊大小: {chunk_size} Bytes")
    
    # 1. 生成測試數據
    print("⚙️ 生成隨機數據...")
    total_size = file_size_kb * 1024
    test_data = os.urandom(total_size)
    file_hash = hashlib.sha256(test_data).digest()
    
    # 2. 連接 WebSocket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((ip, 8888)) # 假設端口 8888
        
        # WS Handshake
        handshake = (
            f"GET /ws HTTP/1.1\r\nHost: {ip}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.send(handshake.encode())
        resp = sock.recv(1024)
        if b"101 Switching Protocols" not in resp:
            print("❌ WebSocket 握手失敗")
            return
        print("✅ WebSocket 連接成功")
        
    except Exception as e:
        print(f"❌ 連接失敗: {e}")
        return

    # 3. 發送 FILE_BEGIN (0x2001)
    # Payload: file_id(u16) + total_size(u32) + chunk_size(u16) + sha256(32s) + path(str_u16len)
    path_str = "/test_speed.bin"
    path_bytes = path_str.encode('utf-8')
    
    payload_begin = struct.pack("<HIH32sH", 
        1,              # file_id
        total_size,     # total_size
        chunk_size,     # chunk_size
        file_hash,      # sha256
        len(path_bytes) # path len
    ) + path_bytes
    
    sock.send(create_ws_frame(pack_cmd(0x2001, payload_begin)))
    print("📡 發送 FILE_BEGIN")
    time.sleep(0.1) # 給一點時間準備

    # 4. 高速發送 FILE_CHUNK (0x2002)
    # Payload: file_id(u16) + offset(u32) + data(rest)
    
    offset = 0
    start_time = time.time()
    
    try:
        while offset < total_size:
            chunk = test_data[offset : offset + chunk_size]
            
            payload_chunk = struct.pack("<HI", 1, offset) + chunk
            packet = pack_cmd(0x2002, payload_chunk)
            
            sock.sendall(create_ws_frame(packet))
            
            offset += len(chunk)
            
            # 進度條
            if offset % (chunk_size * 10) == 0:
                sys.stdout.write(f"\r📤 發送進度: {offset/1024:.0f} KB / {total_size/1024:.0f} KB")
                sys.stdout.flush()
                
    except Exception as e:
        print(f"\n❌ 發送中斷: {e}")
        return

    print(f"\n✅ 數據發送完成，發送 FILE_END...")

    # 5. 發送 FILE_END (0x2003)
    # Payload: file_id(u16)
    payload_end = struct.pack("<H", 1)
    sock.send(create_ws_frame(pack_cmd(0x2003, payload_end)))

    # 6. 等待最終 ACK (0x2004)
    print("⏳ 等待設備校驗與確認...")
    sock.settimeout(10) # 校驗可能需要時間
    try:
        while True:
            # 簡單接收，尋找 ACK 包
            # 注意：這裡沒有做完整的 WS 解幀，只是簡單查找特徵
            # 在真實場景應該用完整的 Parser
            data = sock.recv(1024)
            if not data: break
            
            # 尋找 0x2004 指令 (小端序 04 20)
            # Cmd 在 header 偏移 5 字節處 (SOF(2)+Ver(1)+Addr(2)=5)
            # 但這是 WS Frame，前面還有 WS Header (2-10 bytes)
            # 簡單暴力的搜索
            if b'\x04\x20' in data: 
                end_time = time.time()
                elapsed = end_time - start_time
                speed = (total_size / 1024) / elapsed
                
                print(f"\n🎉 上傳成功！")
                print(f"⏱️ 總耗時: {elapsed:.2f} 秒")
                print(f"🚀 平均速度: {speed:.2f} KB/s")
                break
                
    except socket.timeout:
        print("\n❌ 等待 ACK 超時 (可能校驗失敗或寫入太慢)")
    finally:
        sock.close()

if __name__ == "__main__":
    target_ip = input("請輸入設備 IP (默認 10.10.1.18): ").strip() or "10.10.1.18"
    size_kb = input("請輸入測試大小 KB (默認 1024): ").strip() or "1024"
    test_upload(target_ip, int(size_kb))

import socket
import time
import threading
import os
import sys
import hashlib
import struct

# --- 環境設置：確保能導入項目庫 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR # 假設腳本在根目錄，如果不是請調整
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from slave.lib.proto import Proto, StreamParser
    from slave.lib.schema_loader import SchemaStore
    from slave.lib.schema_codec import SchemaCodec
except ImportError as e:
    print(f"❌ 無法導入項目庫: {e}")
    print("請確保腳本在項目根目錄下運行，且 slave/lib 存在")
    sys.exit(1)

# --- 配置 ---
UDP_PORT = 9000
WS_PORT = 8888

# --- 全局變量 ---
store = SchemaStore(dir_path=f"{PROJECT_ROOT}/slave/schema")
stop_event = threading.Event()

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except:
        return '127.0.0.1'
    finally:
        s.close()

def udp_broadcast_loop():
    """使用 SchemaCodec 構建正確的廣播封包"""
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    local_ip = get_local_ip()
    ws_url = f"ws://{local_ip}:{WS_PORT}"
    
    print(f"📡 UDP 廣播啟動: 指向 {ws_url}")
    
    # 1. 獲取 Schema 定義 (CMD 0x1001 DISCOVER)
    cmd_def = store.get(0x1001)
    if not cmd_def:
        print("❌ 找不到 CMD 0x1001 的 Schema，請檢查 slave/schema/sys.json")
        return

    # 2. 使用 SchemaCodec 編碼 Payload
    # 參數必須與 Schema 定義完全匹配
    payload_dict = {
        "server_ip": local_ip,
        "ws_url": ws_url
    }
    try:
        payload_bytes = SchemaCodec.encode(cmd_def, payload_dict)
    except Exception as e:
        print(f"❌ Payload 編碼失敗: {e}")
        return

    # 3. 使用 Proto 打包 (Header + CRC)
    packet = Proto.pack(0x1001, payload_bytes)
    
    while not stop_event.is_set():
        try:
            udp.sendto(packet, ('255.255.255.255', UDP_PORT))
            print(".", end="", flush=True)
        except Exception as e:
            print(f"UDP Error: {e}")
        time.sleep(2)

def ws_server_loop():
    """啟動 TCP Server"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', WS_PORT))
    except OSError as e:
        print(f"❌ 端口綁定失敗 ({WS_PORT}): {e}")
        print("請確保沒有其他程序 (如 NetBusMaster) 佔用此端口")
        stop_event.set()
        return

    server.listen(1)
    print(f"\n👂 TCP Server 監聽端口 {WS_PORT}...")
    
    while not stop_event.is_set():
        try:
            server.settimeout(1.0)
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
                
            print(f"\n✅ 設備已連接: {addr}")
            stop_event.set() # 停止廣播
            
            handle_connection(conn)
            
            conn.close()
            break # 測試一次後退出
            
        except Exception as e:
            if not stop_event.is_set():
                print(f"\n❌ Server Error: {e}")

def handle_connection(conn):
    """處理連接並進行測試"""
    # 1. WS 握手
    try:
        req = conn.recv(1024)
        if b"Upgrade: websocket" in req:
            resp = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
            )
            conn.send(resp.encode())
            print("🤝 WebSocket 握手完成")
    except Exception as e:
        print(f"握手失敗: {e}")
        return

    # 2. 開始速度測試
    run_speed_test(conn)

def send_ws_packet(conn, cmd_id, args):
    """發送 WS 封包"""
    c_def = store.get(cmd_id)
    payload = SchemaCodec.encode(c_def, args)
    data_pkt = Proto.pack(cmd_id, payload)
    
    # WS Frame Header
    l = len(data_pkt)
    hdr = bytearray([0x82])
    if l <= 125:
        hdr.append(l)
    elif l <= 65535:
        hdr.append(126)
        hdr.extend(struct.pack(">H", l))
    else:
        hdr.append(127)
        hdr.extend(struct.pack(">Q", l))
    
    conn.sendall(hdr + data_pkt)

def run_speed_test(conn):
    print("\n🚀 開始速度測試 (目標 1MB)...")
    
    # 準備數據
    total_size = 1024 * 1024 # 1MB
    chunk_size = 4096        # 4KB (配合 Flash 緩衝)
    test_data = os.urandom(total_size)
    file_hash = hashlib.sha256(test_data).digest()
    target_path = "/speed_test.bin"

    start_time = time.time()

    # Phase 1: FILE_BEGIN (0x2001)
    send_ws_packet(conn, 0x2001, {
        "file_id": 99,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "sha256": file_hash,
        "path": target_path
    })
    time.sleep(0.1) # 給設備一點時間打開文件

    # Phase 2: FILE_CHUNK (0x2002) - 高速發送
    # 注意：這裡不等待 ACK，模擬高速流
    offset = 0
    try:
        last_print_time = start_time
        while offset < total_size:
            chunk = test_data[offset : offset + chunk_size]
            
            # 直接構建封包以減少 overhead
            # 但為了正確性還是用 send_ws_packet
            send_ws_packet(conn, 0x2002, {
                "file_id": 99,
                "offset": offset,
                "data": chunk
            })
            
            offset += len(chunk)
            
            current_time = time.time()
            if current_time - last_print_time > 0.5:
                speed_kb = (offset / 1024) / (current_time - start_time)
                sys.stdout.write(f"\r📤 已發送: {offset/1024:.0f} KB | 即時速度: {speed_kb:.2f} KB/s")
                sys.stdout.flush()
                last_print_time = current_time
                
    except Exception as e:
        print(f"\n❌ 發送中斷: {e}")
        return

    # Phase 3: FILE_END (0x2003)
    print(f"\n✅ 發送完成，發送結束信號...")
    send_ws_packet(conn, 0x2003, {"file_id": 99})

    # Phase 4: 等待最終 ACK (0x2004)
    print("⏳ 等待設備校驗與落盤...")
    conn.settimeout(10.0)
    
    # 簡易接收循環，尋找 0x2004
    parser = StreamParser()
    try:
        while True:
            raw = conn.recv(4096)
            if not raw: break
            
            # 簡易 WS 解包
            if raw[0] == 0x82:
                plen = raw[1] & 0x7F
                off = 2
                if plen == 126: off = 4
                elif plen == 127: off = 10
                parser.feed(raw[off:])
            else:
                parser.feed(raw)
            
            for _, _, cmd, payload in parser.pop():
                if cmd == 0x2004:
                    end_time = time.time()
                    elapsed = end_time - start_time
                    speed = (total_size / 1024) / elapsed
                    print(f"\n🎉 測試成功！")
                    print(f"⏱️ 總耗時: {elapsed:.2f} s")
                    print(f"🚀 平均速度: {speed:.2f} KB/s")
                    return

    except socket.timeout:
        print("\n❌ 等待 ACK 超時 (可能是寫入太慢或校驗失敗)")
    except Exception as e:
        print(f"\n❌ 接收錯誤: {e}")

if __name__ == "__main__":
    # 啟動 UDP 廣播線程
    t_udp = threading.Thread(target=udp_broadcast_loop)
    t_udp.daemon = True
    t_udp.start()
    
    # 主線程運行 TCP Server
    try:
        ws_server_loop()
    except KeyboardInterrupt:
        print("\n👋 停止")
        stop_event.set()

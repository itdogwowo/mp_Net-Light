# test_file_upload_v2.py
"""
PC 端文件上傳測試工具 (支持 File V2 協議)
"""
import sys
import socket
import struct
import json
import hashlib
import time
import os

# -----------------------------------------------------------------------------
# 協議定義 (模擬)
# -----------------------------------------------------------------------------
CMD_FILE_BEGIN  = 0x2001
CMD_FILE_CHUNK  = 0x2002
CMD_FILE_END    = 0x2003
CMD_FILE_ACK    = 0x2004

def pack_cmd(cmd_id, payload_bytes):
    # 簡易打包：[Head:1][Cmd:2][Len:4][Payload]
    # 注意：這裡只模擬 NetBus 的 WS 封裝，實際 NetBus 可能有不同頭部
    # 假設我們走 WS 通道，則需要 WS 封幀
    pass

class NetBusClient:
    def __init__(self, ip, port=8888):
        self.ip = ip
        self.port = port
        self.sock = None
        
    def connect(self):
        print(f"Connecting to {self.ip}:{self.port}...")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip, self.port))
        
        # WS Handshake
        self.sock.send(b"GET / HTTP/1.1\r\n"
                       b"Upgrade: websocket\r\n"
                       b"Connection: Upgrade\r\n"
                       b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                       b"Sec-WebSocket-Version: 13\r\n\r\n")
        resp = self.sock.recv(1024)
        if b"101 Switching Protocols" not in resp:
            raise Exception("Handshake failed")
        print("✅ Connected (WS)")

    def send_ws_frame(self, data):
        # 簡易 WS 封裝 (Binary Frame 0x82)
        header = bytearray([0x82])
        length = len(data)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(127)
            header.extend(struct.pack(">Q", length))
            
        # Masking (Client to Server must mask)
        mask_key = os.urandom(4)
        header.append(0x80 | length if length < 126 else 0) # 修正 header 長度邏輯 (上面有誤，重寫)
        
        # 正確邏輯：
        head = bytearray([0x82])
        if length < 126:
            head.append(0x80 | length)
        elif length < 65536:
            head.append(0x80 | 126)
            head.extend(struct.pack(">H", length))
        else:
            head.append(0x80 | 127)
            head.extend(struct.pack(">Q", length))
            
        head.extend(mask_key)
        
        masked_data = bytearray(length)
        for i in range(length):
            masked_data[i] = data[i] ^ mask_key[i % 4]
            
        self.sock.send(head + masked_data)

    def recv_ws_frame(self):
        # 簡易接收 (假設 Server 不 Mask，且一次收完)
        head = self.sock.recv(2)
        if not head: return None
        
        length = head[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self.sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self.sock.recv(8))[0]
            
        data = b""
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk: break
            data += chunk
            
        return data

    def send_proto(self, cmd_id, payload_dict):
        # 這裡需要一個真正的 Schema Encoder，為了簡化，我們手動打包
        # 假設 Schema 如下：
        # FILE_BEGIN: [file_id:u16][total:u32][chunk:u16][mode:u8][sha:32][path:str]
        
        data = bytearray()
        
        if cmd_id == CMD_FILE_BEGIN:
            data.extend(struct.pack("<H", payload_dict["file_id"]))
            data.extend(struct.pack("<I", payload_dict["total_size"]))
            data.extend(struct.pack("<H", payload_dict["chunk_size"]))
            data.extend(struct.pack("B", payload_dict["save_mode"]))
            data.extend(payload_dict["sha256"])
            path_bytes = payload_dict["path"].encode("utf-8")
            data.extend(struct.pack("<H", len(path_bytes)))
            data.extend(path_bytes)
            
        elif cmd_id == CMD_FILE_CHUNK:
            # [file_id:u16][offset:u32][data:rest]
            data.extend(struct.pack("<H", payload_dict["file_id"]))
            data.extend(struct.pack("<I", payload_dict["offset"]))
            data.extend(payload_dict["data"])
            
        elif cmd_id == CMD_FILE_END:
            # [file_id:u16]
            data.extend(struct.pack("<H", payload_dict["file_id"]))
            
        # 打包 NetBus 頭部 [Cmd:2][Len:4][Data] (Little Endian)
        pkg = struct.pack("<H", cmd_id) + struct.pack("<I", len(data)) + data
        self.send_ws_frame(pkg)

    def wait_ack(self, expect_fid):
        # 等待 ACK
        while True:
            raw = self.recv_ws_frame()
            if not raw: raise Exception("Connection closed")
            
            # 解析頭部
            if len(raw) < 6: continue
            cmd_id = struct.unpack("<H", raw[0:2])[0]
            pl_len = struct.unpack("<I", raw[2:6])[0]
            payload = raw[6:6+pl_len]
            
            if cmd_id == CMD_FILE_ACK:
                fid = struct.unpack("<H", payload[0:2])[0]
                offset = struct.unpack("<I", payload[2:6])[0]
                status = payload[6]
                
                if fid == expect_fid:
                    return status, offset
            
            print(f"⚠️ Ignored cmd: {hex(cmd_id)}")

def upload_file(client, local_path, remote_path, save_mode=1):
    file_size = os.path.getsize(local_path)
    file_id = int(time.time()) % 65536
    
    print(f"📄 Uploading {local_path} ({file_size} bytes)")
    
    # 1. 計算 SHA256
    sha = hashlib.sha256()
    with open(local_path, "rb") as f:
        while True:
            d = f.read(65536)
            if not d: break
            sha.update(d)
    digest = sha.digest()
    
    # 2. Send BEGIN
    print("➡️ Sending BEGIN...")
    client.send_proto(CMD_FILE_BEGIN, {
        "file_id": file_id,
        "total_size": file_size,
        "chunk_size": 4096,
        "save_mode": save_mode,
        "sha256": digest,
        "path": remote_path
    })
    
    status, _ = client.wait_ack(file_id)
    if status != 0:
        print(f"❌ Begin Failed: Status {status}")
        return

    # 3. Send CHUNKS
    chunk_size = 8192 # 配合 PC 端發送能力
    offset = 0
    start_time = time.time()
    
    with open(local_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
            
            client.send_proto(CMD_FILE_CHUNK, {
                "file_id": file_id,
                "offset": offset,
                "data": chunk
            })
            
            # 等待 ACK (每發一包等一次，或滑動窗口)
            # 為了測試極限，我們可以使用「每 N 包等一次」或者「不等待，只在最後等」
            # 但考慮到 Hub 可能滿，簡單起見先每包等
            status, ack_offset = client.wait_ack(file_id)
            if status == 1: # Retry
                print("⚠️ Server busy, retrying...")
                f.seek(offset)
                time.sleep(0.1)
                continue
            elif status != 0:
                print(f"❌ Chunk Error: {status}")
                return
                
            offset += len(chunk)
            print(f"\r📤 {offset/file_size*100:.1f}%", end="")
            
    print("\n➡️ Sending END...")
    client.send_proto(CMD_FILE_END, {"file_id": file_id})
    
    # 等待最終 ACK
    print("⏳ Waiting for final verification...")
    # 可能需要等久一點，因為 Core 1 在寫入
    client.sock.settimeout(30) 
    status, _ = client.wait_ack(file_id)
    
    elapsed = time.time() - start_time
    print(f"✅ Upload Complete! Status: {status}")
    print(f"⚡ Speed: {file_size/1024/1024/elapsed:.2f} MB/s")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_file_upload_v2.py <IP> <File> [SaveMode=1]")
        sys.exit(1)
        
    ip = sys.argv[1]
    file = sys.argv[2]
    mode = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    
    client = NetBusClient(ip)
    client.connect()
    upload_file(client, file, f"/sd/{os.path.basename(file)}", mode)

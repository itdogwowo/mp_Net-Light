import socket
import time
import threading
import os
import hashlib
import struct
import json

# 假設你的專案目錄結構中包含這些自定義庫
from lib.proto import Proto, StreamParser
from lib.schema_loader import SchemaStore
from lib.schema_codec import SchemaCodec

# ==================== 全局配置 ====================
DEBUG_MODE = True  # 🚀 開啟後會印出所有 Raw Hex 數據，用於診斷通訊問題

class PCTestTool:
    def __init__(self):
        # 1. 載入 Schema 定義
        self.store = SchemaStore(dir_path="./schema")
        # 2. 設備管理表 { slave_id: { info } }
        self.slaves = {} 
        self.running = True
        self.local_ip = self.get_local_ip()

    def get_local_ip(self):
        """獲取 PC 當前網絡 IP"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except: return '127.0.0.1'
        finally: s.close()

    # ==================== 通訊核心 (Server) ====================
    def start_ws_server(self):
        """啟動 WebSocket 控制服務器"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 8000))
        s.listen(10)
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except: break

    def handle_client(self, conn, addr):
        """處理單個設備連接線程"""
        curr_id = f"PENDING_{addr[1]}"
        try:
            # --- WebSocket 握手 ---
            raw_req = conn.recv(1024).decode()
            if "Upgrade: websocket" not in raw_req:
                conn.close()
                return

            resp = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
            )
            conn.send(resp.encode())
            
            # --- 初始化設備槽位 ---
            self.slaves[curr_id] = {
                "conn": conn, 
                "addr": addr, 
                "ack_event": threading.Event(),
                "parser": StreamParser(), 
                "last_seen": time.time(),
                "mem_free": 0, 
                "uptime": 0, 
                "is_identified": False,
                "last_ack_off": -1
            }
            
            p = self.slaves[curr_id]["parser"]
            print(f"\n✨ [Conn] New WebSocket Link: {addr[0]}:{addr[1]}")

            while self.running:
                raw = conn.recv(4096)
                if not raw: break
                
                if DEBUG_MODE:
                    print(f"\n📥 [RECV HEX] {len(raw)} bytes: {raw.hex(' ')}")
                
                # 解法 WebSocket 幀 (初步處理 Binary 0x82)
                # 判斷是否為正常的 WS Binary Frame 或 Raw Proto
                if raw[0] == 0x82:
                    payload_len = raw[1] & 0x7F
                    offset = 2
                    if payload_len == 126: offset = 4
                    elif payload_len == 127: offset = 10
                    payload_data = raw[offset:]
                else:
                    payload_data = raw # 可能是直接的 Proto 封裝

                # 送入協議解析器 (處理分包與包頭校驗)
                p.feed(payload_data)
                for ver, addr_pkt, cmd, payload in p.pop():
                    if DEBUG_MODE:
                        print(f"📦 [PROTO] CMD: {hex(cmd)} | Payload: {payload.hex(' ')}")
                    
                    # 進入業務邏輯分發
                    curr_id = self.dispatch(curr_id, cmd, payload)
                            
        except Exception as e:
            print(f"\n❌ [Error] {curr_id} exception: {e}")
        finally:
            if curr_id in self.slaves: 
                del self.slaves[curr_id]
            conn.close()
            print(f"🔌 [Conn] {curr_id} left.")

    def dispatch(self, cid, cmd, payload):
        """核心分發器：負責解析數據並維持設備狀態表"""
        try:
            c_def = self.store.get(cmd)
            if not c_def: return cid
            args = SchemaCodec.decode(c_def, payload)
            
            # --- 🚀 關鍵：從任何包含 ID 的包中識別設備 ---
            real_id = None
            
            # 情況 A: 收到心跳包 (0x1201)
            if cmd == 0x1201:
                real_id = args.get("slave_id")
                # 更新 Dashboard 基礎數據
                if cid in self.slaves:
                    self.slaves[cid].update({
                        "mem_free": args.get("mem_free", 0),
                        "uptime": args.get("uptime_ms", 0)
                    })

            # 情況 B: 收到狀態回覆包 (0x1102)
            elif cmd == 0x1102:
                try:
                    status_data = json.loads(args["status_json"])
                    real_id = status_data.get("id") # 這裡是你的 "ESP32" 或 MAC
                    
                    # 🚀 同步 JSON 數據到 Dashboard 欄位，這樣 Dashboard 就不會是 0 了
                    if cid in self.slaves:
                        self.slaves[cid].update({
                            "mem_free": status_data.get("mem_free", 0),
                            "uptime": status_data.get("uptime_ms", 0)
                        })
                    
                    print(f"\n📊 [Status Response] From {cid}:")
                    print(json.dumps(status_data, indent=2))
                except:
                    print(f"⚠️ Failed to parse status JSON from {cid}")

            # --- 🚀 執行 ID 更名邏輯 ---
            if real_id and real_id != cid:
                if cid in self.slaves:
                    # 搬移數據到新 Key
                    self.slaves[real_id] = self.slaves.pop(cid)
                    self.slaves[real_id]["is_identified"] = True
                    print(f"\n🆔 [Identify] {cid} -> {real_id}")
                    return real_id # 返回新 ID 給 handle_connection
            
            # 處理其他指令 (如 FILE_ACK)
            if cmd == 0x2004:
                if cid in self.slaves:
                    self.slaves[cid]["last_ack_off"] = args["offset"]
                    self.slaves[cid]["ack_event"].set()

            # 更新最後見到時間
            if cid in self.slaves:
                self.slaves[cid]["last_seen"] = time.time()
                
            return cid
        except Exception as e:
            print(f"⚠️ [Dispatch Error] {e}")
            return cid

    # ==================== 指令發送 ====================
    def send_to_targets(self, targets, cmd_id, args):
        c_def = self.store.get(cmd_id)
        if not c_def: return
        
        # 1. 封裝 Proto 包
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        
        # 2. 封裝 WebSocket 幀 Header
        length = len(data_pkt)
        ws_hdr = bytearray([0x82]) # Binary Frame
        if length <= 125:
            ws_hdr.append(length)
        elif length <= 65535:
            ws_hdr.append(126)
            ws_hdr.extend(struct.pack(">H", length))
        else:
            ws_hdr.append(127)
            ws_hdr.extend(struct.pack(">Q", length))
        
        full_pkt = ws_hdr + data_pkt
        
        if DEBUG_MODE and cmd_id != 0x1202: # 過濾掉頻繁的心跳回覆打印
            print(f"📤 [SEND] CMD {hex(cmd_id)}: {full_pkt.hex(' ')}")
            
        for tid in targets:
            if tid in self.slaves:
                try: self.slaves[tid]["conn"].sendall(full_pkt)
                except: pass

    # ==================== 選單功能 ====================
    def select_targets(self):
        ids = list(self.slaves.keys())
        if not ids:
            print("❌ No devices online.")
            return []
        print("\nOnline Devices:")
        for i, sid in enumerate(ids):
            print(f"{i+1}. {sid} ({self.slaves[sid]['addr'][0]})")
        print("a. All")
        res = input("👉 Select: ").strip()
        if res.lower() == 'a': return ids
        try: return [ids[int(res)-1]]
        except: return []

    def upload_file_task(self):
        targets = self.select_targets()
        if not targets: return
        
        files = [f for f in os.listdir('.') if f.endswith(('.bin', '.py', '.json', '.pxld'))]
        if not files: return
        
        for i, f in enumerate(files): print(f"{i+1}. {f} ({os.path.getsize(f)} bytes)")
        try: 
            local_name = files[int(input("📂 Choose file: "))-1]
        except: return
        
        remote_path = input(f"💾 Remote Path [/{local_name}]: ") or f"/{local_name}"
        
        with open(local_name, "rb") as f:
            data = f.read()
        
        sha = hashlib.sha256(data).digest()
        f_id = 100
        chunk_size = 1024
        
        print(f"\n🚀 Uploading to {targets}...")
        self.send_to_targets(targets, 0x2001, {
            "file_id": f_id, "total_size": len(data), 
            "chunk_size": chunk_size, "sha256": sha, "path": remote_path
        })
        
        for off in range(0, len(data), chunk_size):
            chunk = data[off : off + chunk_size]
            for tid in targets:
                if tid not in self.slaves: continue
                # 停等機制
                retry = 0
                while retry < 5:
                    self.slaves[tid]["ack_event"].clear()
                    self.send_to_targets([tid], 0x2002, {"file_id": f_id, "offset": off, "data": chunk})
                    if self.slaves[tid]["ack_event"].wait(timeout=1.0):
                        break
                    retry += 1
                    print(f"⚠️ [{tid}] Retry {retry}/5 for offset {off}")
            
            print(f"  ﹂ 📤 Progress: {min(off+chunk_size, len(data))}/{len(data)} bytes", end='\r')
            
        self.send_to_targets(targets, 0x2003, {"file_id": f_id})
        print("\n✅ Upload Complete.")

    def run(self):
        """主入口"""
        # 啟動背景服務器線程
        threading.Thread(target=self.start_ws_server, daemon=True).start()
        
        while True:
            print(f"\n--- 🚀 NetBus PC Console ({self.local_ip}) ---")
            print("1. Broadcast Discovery")
            print("2. Dashboard (Connections)")
            print("3. Active Health Check (Query Status)")
            print("4. Upload File")
            print("d. Toggle Debug Mode")
            print("q. Exit")
            
            c = input("\n👉 Choice: ").lower()
            if c == '1':
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                p_data = SchemaCodec.encode(self.store.get(0x1001), {"server_ip": self.local_ip, "ws_url": f"ws://{self.local_ip}:8000/ws"})
                s.sendto(Proto.pack(0x1001, p_data), ('255.255.255.255', 9000))
                s.close()
                print("📡 Discovery Broadcast sent.")
                
            elif c == '2':
                print("-" * 85)
                print(f"{'Slave ID':<20} | {'IP':<15} | {'FreeMem':<10} | {'Uptime':<10} | {'Last Seen'}")
                now = time.time()
                for sid, info in self.slaves.items():
                    print(f"{sid:<20} | {info['addr'][0]:<15} | {info['mem_free']:<10} | {info['uptime']//1000:<10}s | {int(now-info['last_seen'])}s ago")
                print("-" * 85)
                
            elif c == '3':
                ts = self.select_targets()
                if ts: self.send_to_targets(ts, 0x1101, {"query_type": 1})
                
            elif c == '4':
                self.upload_file_task()
                
            elif c == 'd':
                global DEBUG_MODE
                DEBUG_MODE = not DEBUG_MODE
                print(f"🛠️ Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
                
            elif c == 'q':
                self.running = False
                break

if __name__ == "__main__":
    PCTestTool().run()
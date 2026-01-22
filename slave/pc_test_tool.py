import socket, time, threading, os, hashlib, struct
from lib.proto import Proto, StreamParser
from lib.schema_loader import SchemaStore
from lib.schema_codec import SchemaCodec

class PCTestTool:
    def __init__(self):
        self.store = SchemaStore(dir_path="./schema")
        self.slaves = {} # {mac_id: {"conn": conn, "addr": addr, "ack_event": Event, "last_ack_off": -1}}
        self.running = True
        self.local_ip = self.get_local_ip()

    def get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except: return '127.0.0.1'
        finally: s.close()

    def start_ws_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 8000))
        s.listen(10)
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(target=self.handle_new_connection, args=(conn, addr), daemon=True).start()
            except: break

    def handle_new_connection(self, conn, addr):
        mac_id = "Unknown"
        try:
            request = conn.recv(1024).decode()
            if "Upgrade: websocket" in request:
                try: mac_id = request.split("GET /ws/")[1].split(" ")[0].strip()
                except: mac_id = f"DEV_{addr[1]}"
                
                resp = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
                conn.send(resp.encode())
                
                self.slaves[mac_id] = {
                    "conn": conn, "addr": addr, "ack_event": threading.Event(),
                    "parser": StreamParser(), "last_ack_off": -1
                }
                print(f"\n✨ [Fleet] Slave Connected: {mac_id} @ {addr[0]}")
                
                p = self.slaves[mac_id]["parser"]
                while mac_id in self.slaves:
                    raw = conn.recv(4096)
                    if not raw: break
                    data = raw[2:] if raw[0] == 0x82 else raw
                    p.feed(data)
                    for ver, addr_pkt, cmd, payload in p.pop():
                        if cmd == 0x2004: # FILE_ACK
                            args = SchemaCodec.decode(self.store.get(0x2004), payload)
                            self.slaves[mac_id]["last_ack_off"] = args["offset"]
                            self.slaves[mac_id]["ack_event"].set()
                        else:
                            c_def = self.store.get(cmd)
                            name = c_def['name'] if c_def else hex(cmd)
                            args = SchemaCodec.decode(c_def, payload) if c_def else payload
                            print(f"\n📥 [{mac_id}] {name}: {args}")
        except: pass
        finally:
            if mac_id in self.slaves: del self.slaves[mac_id]
            conn.close()

    def select_file(self):
        files = [f for f in os.listdir('.') if f.endswith(('.bin', '.json', '.pxld'))]
        if not files:
            print("❌ No data files found in current directory.")
            return None
        print("\n--- Local Files ---")
        for i, f in enumerate(files):
            print(f"{i+1}. {f} ({os.path.getsize(f)} bytes)")
        c = input("👉 Select file number: ")
        try: return files[int(c)-1]
        except: return None

    def select_slaves(self):
        if not self.slaves:
            print("❌ No slaves connected."); return []
        ids = list(self.slaves.keys())
        print("\n--- Available Slaves ---")
        for i, m_id in enumerate(ids):
            print(f"{i+1}. {m_id} ({self.slaves[m_id]['addr'][0]})")
        print("a. ALL Slaves")
        choice = input("👉 Select target (number or 'a'): ").strip()
        if choice.lower() == 'a': return ids
        try: return [ids[int(choice)-1]]
        except: return []

    def send_to_targets(self, targets, cmd_id, args):
        c_def = self.store.get(cmd_id)
        pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        length = len(pkt)
        ws_hdr = bytearray([0x82])
        if length <= 125: ws_hdr.append(length)
        elif length <= 65535: ws_hdr.append(126); ws_hdr.extend(struct.pack(">H", length))
        else: ws_hdr.append(127); ws_hdr.extend(struct.pack(">Q", length))
        
        data = ws_hdr + pkt
        for m_id in targets:
            if m_id in self.slaves:
                try: self.slaves[m_id]["conn"].sendall(data)
                except: pass

    def upload_to_targets(self, targets, local_path, remote_path):
        with open(local_path, "rb") as f: data = f.read()
        sha_bytes = hashlib.sha256(data).digest()
        sha_hex = hashlib.sha256(data).hexdigest()
        f_id = 777
        chunk_size = 1024
        
        print(f"\n🚀 Starting Upload: {local_path} (Hash: {sha_hex[:16]}...)")
        self.send_to_targets(targets, 0x2001, {"file_id": f_id, "total_size": len(data), "chunk_size": chunk_size, "sha256": sha_bytes, "path": remote_path})
        time.sleep(0.5)

        for offset in range(0, len(data), chunk_size):
            chunk = data[offset : offset + chunk_size]
            
            # 🚀 嚴格停等重試機制
            for m_id in targets:
                retry_count = 0
                while m_id in self.slaves:
                    self.slaves[m_id]["ack_event"].clear()
                    # 發送/重發當前 Chunk
                    self.send_to_targets([m_id], 0x2002, {"file_id": f_id, "offset": offset, "data": chunk})
                    
                    # 等待 ACK (設定短超時以便重試)
                    if self.slaves[m_id]["ack_event"].wait(timeout=1.5):
                        break # 收到 ACK，跳出重試循環
                    
                    retry_count += 1
                    if retry_count > 10: # 1.5s * 10 = 約 15秒
                        print(f"\n❌ [{m_id}] Failed after 15s retries. Aborting.")
                        return
                    print(f"\n⚠️  [{m_id}] Timeout! Retrying {retry_count}/10 at offset {offset}...")

            done = offset + len(chunk)
            print(f"   ﹂ 📤 Progress: {done/len(data)*100:6.2f}% ({done}/{len(data)})", end="\r")
            
        self.send_to_targets(targets, 0x2003, {"file_id": f_id})
        print(f"\n" + "="*40)
        print(f"✅ [PC] Upload Command Sent.")
        print(f"📄 [File] {local_path} ({len(data)} bytes)")
        print(f"🔒 [SHA256] {sha_hex}")
        print("="*40)
        print(f"⏳ Waiting for Slave verification...")
        time.sleep(2.0)

    def upload_file_interactive(self):
        """
        交互式上傳流程：選擇 Slave -> 選擇文件 -> 輸入遠端路徑
        """
        # 1. 選擇目標
        targets = self.select_slaves()
        if not targets:
            return

        # 2. 選擇本地文件
        local_fname = self.select_file()
        if not local_fname:
            return

        # 3. 🚀 輸入遠端路徑
        default_remote = "/" + local_fname
        print(f"\n📁 Local File: {local_fname}")
        remote_path = input(f"💾 Enter remote path (Press Enter for '{default_remote}'): ").strip()
        if not remote_path:
            remote_path = default_remote
        elif not remote_path.startswith('/'):
            remote_path = '/' + remote_path

        # 4. 執行上傳
        self.upload_to_targets(targets, local_fname, remote_path)

    def run(self):
        threading.Thread(target=self.start_ws_server, daemon=True).start()
        while True:
            print(f"\n--- 🚀 NetBus Fleet Controller ({self.local_ip}) ---")
            print("1. Discovery (Broadcasting PC IP)")
            print("2. Upload File (Custom Local & Remote Path)") # 🚀 修改描述
            print("3. Stream Control (Local Sync Mode)")
            print("q. Exit")
            
            cmd = input("\n👉 Choice: ").lower()
            if cmd == '1':
                # 發送廣播邏輯...
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                pkt = Proto.pack(0x1001, SchemaCodec.encode(self.store.get(0x1001), {
                    "server_ip": self.local_ip, 
                    "ws_url": f"ws://{self.local_ip}:8000/ws"
                }))
                s.sendto(pkt, ('255.255.255.255', 9000)); s.close()
                print("📡 Discovery Broadcast sent.")
            elif cmd == '2':
                self.upload_file_interactive() # 🚀 使用新的交互函數
            elif cmd == '3':
                # 串流控制邏輯...
                targets = self.select_slaves()
                if not targets: continue
                sub = input("  (1) Start (2) Stop: ")
                if sub == '1': self.send_to_targets(targets, 0x3001, {"fps": 40, "mode": "local"})
                else: self.send_to_targets(targets, 0x3002, {})
            elif cmd == 'q': break

if __name__ == "__main__":
    PCTestTool().run()
"""
PC 端測試工具
═══════════════════════════════════════════════════════
功能:
1. 廣播發現設備
2. 上傳 .bin 文件
3. 發送 Stream 指令
4. 監控狀態
"""
import socket
import time
import threading
import os
import hashlib
import struct
import json

from lib.proto import Proto, StreamParser
from lib.schema_loader import SchemaStore
from lib.schema_codec import SchemaCodec

DEBUG_MODE = True

class PCTestTool:
    def __init__(self):
        self.store = SchemaStore(dir_path="./schema")
        self.slaves = {}
        self.running = True
        self.local_ip = self.get_local_ip()
    
    def get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except:
            return '127.0.0.1'
        finally:
            s.close()
    
    # ==================== Server ====================
    
    def start_ws_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 8000))
        s.listen(10)
        print(f"🚀 WebSocket Server @ {self.local_ip}:8000")
        
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except:
                break
    
    def handle_client(self, conn, addr):
        curr_id = f"PENDING_{addr[1]}"
        
        try:
            # WebSocket 握手
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
            
            # 初始化槽位
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
            print(f"\n✨ [Conn] {addr[0]}:{addr[1]}")
            
            while self.running:
                raw = conn.recv(4096)
                if not raw:
                    break
                
                if DEBUG_MODE:
                    print(f"📥 [RECV] {len(raw)} bytes: {raw.hex(' ')}")
                
                # 解 WebSocket 幀
                if raw[0] == 0x82:
                    payload_len = raw[1] & 0x7F
                    offset = 2
                    if payload_len == 126:
                        offset = 4
                    elif payload_len == 127:
                        offset = 10
                    payload_data = raw[offset:]
                else:
                    payload_data = raw
                
                p.feed(payload_data)
                for ver, addr_pkt, cmd, payload in p.pop():
                    if DEBUG_MODE:
                        print(f"📦 [PROTO] CMD: {hex(cmd)}")
                    
                    curr_id = self.dispatch(curr_id, cmd, payload)
        
        except Exception as e:
            print(f"\n❌ [Error] {curr_id}: {e}")
        finally:
            if curr_id in self.slaves:
                del self.slaves[curr_id]
            conn.close()
            print(f"🔌 [Conn] {curr_id} left")
    
    def dispatch(self, cid, cmd, payload):
        try:
            c_def = self.store.get(cmd)
            if not c_def:
                return cid
            
            args = SchemaCodec.decode(c_def, payload)
            
            real_id = None
            
            if cmd == 0x1201:  # HEARTBEAT
                real_id = args.get("slave_id")
                if cid in self.slaves:
                    self.slaves[cid].update({
                        "mem_free": args.get("mem_free", 0),
                        "uptime": args.get("uptime_ms", 0)
                    })
            
            elif cmd == 0x1102:  # STATUS_RSP
                try:
                    status_data = json.loads(args["status_json"])
                    real_id = status_data.get("id")
                    
                    if cid in self.slaves:
                        self.slaves[cid].update({
                            "mem_free": status_data.get("mem_free", 0),
                            "uptime": status_data.get("uptime_ms", 0)
                        })
                    
                    print(f"\n📊 [Status] From {cid}:")
                    print(json.dumps(status_data, indent=2))
                except:
                    pass
            
            elif cmd == 0x2004:  # FILE_ACK
                if cid in self.slaves:
                    self.slaves[cid]["last_ack_off"] = args["offset"]
                    self.slaves[cid]["ack_event"].set()
            
            elif cmd == 0x3008:  # STREAM_READY_ACK
                status_map = ["NOT_READY", "READY", "QUEUE_FULL", "LOADING"]
                status_str = status_map[args["status"]]
                print(f"\n📤 [READY_ACK] Block {args['block_id']} → {status_str} (Slot {args['slot']})")
            
            elif cmd == 0x3012:  # BLOCK_COMPLETE
                print(f"\n🏁 [BLOCK_COMPLETE] Block {args['block_id']}, FPS {args['actual_fps']/100:.2f}, Freed Slot {args['freed_slot']}")
            
            elif cmd == 0x3015:  # STATUS_RSP
                try:
                    status_data = json.loads(args["status_json"])
                    print(f"\n📊 [Stream Status]:")
                    print(json.dumps(status_data, indent=2))
                except:
                    pass
            
            elif cmd == 0x3016:  # ERROR
                print(f"\n❌ [Stream Error] Code {args['error_code']}, Block {args['block_id']}: {args['message']}")
            
            # ID 更名
            if real_id and real_id != cid:
                if cid in self.slaves:
                    self.slaves[real_id] = self.slaves.pop(cid)
                    self.slaves[real_id]["is_identified"] = True
                    print(f"\n🆔 [Identify] {cid} → {real_id}")
                    return real_id
            
            if cid in self.slaves:
                self.slaves[cid]["last_seen"] = time.time()
            
            return cid
        
        except Exception as e:
            print(f"⚠️ [Dispatch Error] {e}")
            return cid
    
    # ==================== 發送 ====================
    
    def send_to_targets(self, targets, cmd_id, args):
        c_def = self.store.get(cmd_id)
        if not c_def:
            return
        
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        
        length = len(data_pkt)
        ws_hdr = bytearray([0x82])
        if length <= 125:
            ws_hdr.append(length)
        elif length <= 65535:
            ws_hdr.append(126)
            ws_hdr.extend(struct.pack(">H", length))
        else:
            ws_hdr.append(127)
            ws_hdr.extend(struct.pack(">Q", length))
        
        full_pkt = ws_hdr + data_pkt
        
        if DEBUG_MODE and cmd_id != 0x1202:
            print(f"📤 [SEND] CMD {hex(cmd_id)}")
        
        for tid in targets:
            if tid in self.slaves:
                try:
                    self.slaves[tid]["conn"].sendall(full_pkt)
                except:
                    pass
    
    # ==================== 選單 ====================
    
    def select_targets(self):
        ids = list(self.slaves.keys())
        if not ids:
            print("❌ No devices online")
            return []
        
        print("\nOnline Devices:")
        for i, sid in enumerate(ids):
            print(f"{i+1}. {sid} ({self.slaves[sid]['addr'][0]})")
        print("a. All")
        
        res = input("👉 Select: ").strip()
        if res.lower() == 'a':
            return ids
        try:
            return [ids[int(res)-1]]
        except:
            return []
    
    def upload_file_task(self):
        targets = self.select_targets()
        if not targets:
            return
        
        files = [f for f in os.listdir('.') if f.endswith(('.bin', '.py', '.json'))]
        if not files:
            print("❌ No files found")
            return
        
        print("\nAvailable Files:")
        for i, f in enumerate(files):
            size = os.path.getsize(f)
            print(f"{i+1}. {f} ({size} bytes)")
        
        try:
            local_name = files[int(input("📂 Choose file: "))-1]
        except:
            return
        
        remote_path = input(f"💾 Remote Path [/{local_name}]: ") or f"/{local_name}"
        
        with open(local_name, "rb") as f:
            data = f.read()
        
        sha = hashlib.sha256(data).digest()
        f_id = 100
        chunk_size = 1024
        
        print(f"\n🚀 Uploading to {targets}...")
        
        self.send_to_targets(targets, 0x2001, {
            "file_id": f_id,
            "total_size": len(data),
            "chunk_size": chunk_size,
            "sha256": sha,
            "path": remote_path
        })
        
        for off in range(0, len(data), chunk_size):
            chunk = data[off : off + chunk_size]
            
            for tid in targets:
                if tid not in self.slaves:
                    continue
                
                retry = 0
                while retry < 5:
                    self.slaves[tid]["ack_event"].clear()
                    self.send_to_targets([tid], 0x2002, {
                        "file_id": f_id,
                        "offset": off,
                        "data": chunk
                    })
                    
                    if self.slaves[tid]["ack_event"].wait(timeout=1.0):
                        break
                    
                    retry += 1
                    print(f"⚠️ [{tid}] Retry {retry}/5 for offset {off}")
            
            print(f"  📤 Progress: {min(off+chunk_size, len(data))}/{len(data)} bytes", end='\r')
        
        self.send_to_targets(targets, 0x2003, {"file_id": f_id})
        print("\n✅ Upload Complete")
    
    def stream_config_task(self):
        targets = self.select_targets()
        if not targets:
            return
        
        print("\n🔧 Stream Configuration:")
        num_leds = int(input("LED 數量 [2000]: ") or 2000)
        f_per_block = int(input("每 Block 幀數 [500]: ") or 500)
        total_blocks = int(input("總 Block 數 [100]: ") or 100)
        fps = int(input("FPS [40]: ") or 40)
        mode = int(input("模式 (0=Flash, 1=RAM, 2=混合) [2]: ") or 2)
        data_path = input("數據路徑 [/data/]: ") or "/data/"
        num_buffers = int(input("槽位數 [3]: ") or 3)
        report_interval = int(input("回報間隔 (ms) [5000]: ") or 5000)
        
        self.send_to_targets(targets, 0x3001, {
            "num_leds": num_leds,
            "f_per_block": f_per_block,
            "total_blocks": total_blocks,
            "fps": fps,
            "mode": mode,
            "data_path": data_path,
            "num_buffers": num_buffers,
            "report_interval": report_interval
        })
        
        print("✅ Config Sent")
    
    def stream_state_set_task(self):
        targets = self.select_targets()
        if not targets:
            return
        
        block_id = int(input("Block ID: "))
        frame_offset = int(input("Frame Offset [0]: ") or 0)
        priority = int(input("Priority (0=Queue, 1=Immediate) [0]: ") or 0)
        source = int(input("Source (0=Auto, 1=Flash, 2=RAM) [0]: ") or 0)
        
        self.send_to_targets(targets, 0x3009, {
            "block_id": block_id,
            "frame_offset": frame_offset,
            "priority": priority,
            "source": source
        })
        
        print("✅ STATE_SET Sent")
    
    def stream_play_task(self):
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x300A, {})
        print("▶️ PLAY Sent")
    
    def stream_stop_task(self):
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x3002, {})
        print("⏹️ STOP Sent")
    
    def stream_status_task(self):
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x3014, {})
        print("📊 Status Query Sent")
    
    # ==================== 主循環 ====================
    
    def run(self):
        threading.Thread(target=self.start_ws_server, daemon=True).start()
        
        while True:
            print(f"\n--- 🚀 NetBus PC Console ({self.local_ip}) ---")
            print("1. Broadcast Discovery")
            print("2. Dashboard")
            print("3. Upload File")
            print("4. Stream Config")
            print("5. Stream State Set")
            print("6. Stream Play")
            print("7. Stream Stop")
            print("8. Stream Status Query")
            print("d. Toggle Debug")
            print("q. Exit")
            
            c = input("\n👉 Choice: ").lower()
            
            if c == '1':
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                p_data = SchemaCodec.encode(self.store.get(0x1001), {
                    "server_ip": self.local_ip,
                    "ws_url": f"ws://{self.local_ip}:8000/ws"
                })
                s.sendto(Proto.pack(0x1001, p_data), ('255.255.255.255', 9000))
                s.close()
                print("📡 Discovery Sent")
            
            elif c == '2':
                print("-" * 80)
                print(f"{'Slave ID':<20} | {'IP':<15} | {'FreeMem':<10} | {'Uptime':<10}")
                now = time.time()
                for sid, info in self.slaves.items():
                    print(f"{sid:<20} | {info['addr'][0]:<15} | {info['mem_free']:<10} | {info['uptime']//1000:<10}s")
                print("-" * 80)
            
            elif c == '3':
                self.upload_file_task()
            
            elif c == '4':
                self.stream_config_task()
            
            elif c == '5':
                self.stream_state_set_task()
            
            elif c == '6':
                self.stream_play_task()
            
            elif c == '7':
                self.stream_stop_task()
            
            elif c == '8':
                self.stream_status_task()
            
            elif c == 'd':
                global DEBUG_MODE
                DEBUG_MODE = not DEBUG_MODE
                print(f"🛠️ Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
            
            elif c == 'q':
                self.running = False
                break

if __name__ == "__main__":
    PCTestTool().run()
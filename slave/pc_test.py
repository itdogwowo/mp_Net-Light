# pc_test_tool.py
"""
PC 測試工具 - 完整版
═══════════════════════════════════════════════════════
功能:
- WebSocket Server (控制通道)
- UDP Discovery (設備發現)
- File Upload (文件上傳)
- Stream Control (播放控制)
- Health Monitor (健康監控)
"""
import socket
import time
import threading
import os
import hashlib
import struct
import json

# 引用協議庫
from lib.proto import Proto, StreamParser
from lib.schema_loader import SchemaStore
from lib.schema_codec import SchemaCodec

# ══════════════════════════════════════════════════
# 全局配置
# ══════════════════════════════════════════════════

DEBUG_MODE = False  # 開啟後顯示所有二進制封包

# 狀態碼常量
STATUS_NOT_READY = 0
STATUS_READY = 1
STATUS_QUEUE_FULL = 2
STATUS_LOADING = 3

# 優先級常量
PRIORITY_QUEUE = 0
PRIORITY_IMMEDIATE = 1
PRIORITY_PRELOAD = 2

# ══════════════════════════════════════════════════
# PC 測試工具主類
# ══════════════════════════════════════════════════

class PCTestTool:
    def __init__(self):
        # 載入 Schema
        self.store = SchemaStore(dir_path="./schema")
        
        # 設備管理表
        self.slaves = {}  # {slave_id: {conn, parser, state, ...}}
        
        # 運行控制
        self.running = True
        self.local_ip = self.get_local_ip()
        
        # ACK 等待隊列
        self.ack_queue = {}  # {slave_id: {cmd: event}}
        
        print(f"🚀 PC Test Tool Initialized | IP: {self.local_ip}")
    
    def get_local_ip(self):
        """獲取 PC 當前網絡 IP"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except:
            return '127.0.0.1'
        finally:
            s.close()
    
    # ══════════════════════════════════════════════════
    # WebSocket Server
    # ══════════════════════════════════════════════════
    
    def start_ws_server(self):
        """啟動 WebSocket 控制服務器"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 8000))
        s.listen(10)
        
        print(f"🌐 WebSocket Server listening on {self.local_ip}:8000")
        
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(
                    target=self.handle_client,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except:
                break
        
        s.close()
    
    def handle_client(self, conn, addr):
        """處理單個設備連接"""
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
            
            # 初始化設備槽位
            self.slaves[curr_id] = {
                "conn": conn,
                "addr": addr,
                "parser": StreamParser(),
                "last_seen": time.time(),
                "is_identified": False,
                # 狀態數據
                "mem_free": 0,
                "uptime_ms": 0,
                "render_fps": 0,
                # Stream 狀態
                "next_block": 0,
                "queue_full": False,
                # ACK 緩存
                "last_ack": {}
            }
            
            # 初始化 ACK 隊列
            self.ack_queue[curr_id] = {}
            
            p = self.slaves[curr_id]["parser"]
            
            print(f"\n✨ [Conn] New Connection: {addr[0]}:{addr[1]}")
            
            while self.running:
                raw = conn.recv(4096)
                if not raw:
                    break
                
                if DEBUG_MODE:
                    print(f"\n📥 [RECV] {len(raw)} bytes: {raw.hex(' ')}")
                
                # 解包 WebSocket Binary Frame
                if raw[0] == 0x82:
                    pl_len = raw[1] & 0x7F
                    offset = 2
                    if pl_len == 126:
                        offset = 4
                    elif pl_len == 127:
                        offset = 10
                    payload_data = raw[offset:]
                else:
                    payload_data = raw
                
                # 送入協議解析器
                p.feed(payload_data)
                
                for ver, addr_pkt, cmd, payload in p.pop():
                    if DEBUG_MODE:
                        print(f"📦 [PROTO] CMD: {hex(cmd)}")
                    
                    # 分發處理
                    curr_id = self.dispatch(curr_id, cmd, payload)
        
        except Exception as e:
            print(f"\n❌ [Error] {curr_id}: {e}")
        
        finally:
            if curr_id in self.slaves:
                del self.slaves[curr_id]
            if curr_id in self.ack_queue:
                del self.ack_queue[curr_id]
            conn.close()
            print(f"🔌 [Conn] {curr_id} disconnected")
    
    # ══════════════════════════════════════════════════
    # 消息分發器
    # ══════════════════════════════════════════════════
    
    def dispatch(self, cid, cmd, payload):
        """核心分發器"""
        try:
            c_def = self.store.get(cmd)
            if not c_def:
                return cid
            
            args = SchemaCodec.decode(c_def, payload)
            
            # ── ID 識別 ──
            real_id = None
            
            if cmd == 0x1201:  # HEARTBEAT
                real_id = args.get("slave_id")
                if cid in self.slaves:
                    self.slaves[cid].update({
                        "mem_free": args.get("mem_free", 0),
                        "uptime_ms": args.get("uptime_ms", 0)
                    })
            
            elif cmd == 0x1102:  # STATUS_RSP
                try:
                    status_data = json.loads(args["status_json"])
                    real_id = status_data.get("id")
                    
                    if cid in self.slaves:
                        self.slaves[cid].update({
                            "mem_free": status_data.get("mem_free", 0),
                            "uptime_ms": status_data.get("uptime_ms", 0),
                            "render_fps": status_data.get("render_fps", 0)
                        })
                    
                    print(f"\n📊 [Status] {cid}:")
                    print(f"  Mem Free: {status_data.get('mem_free', 0) // 1024} KB")
                    print(f"  Render FPS: {status_data.get('render_fps', 0)}")
                    print(f"  Stream Mode: {status_data.get('stream_mode', 'idle')}")
                except:
                    pass
            
            # ID 更名
            if real_id and real_id != cid:
                if cid in self.slaves:
                    self.slaves[real_id] = self.slaves.pop(cid)
                    self.slaves[real_id]["is_identified"] = True
                    
                    if cid in self.ack_queue:
                        self.ack_queue[real_id] = self.ack_queue.pop(cid)
                    
                    print(f"\n🆔 [Identify] {cid} → {real_id}")
                    cid = real_id
            
            # ── 處理回報 ──
            
            if cmd == 0x3008:  # STREAM_READY_ACK
                block_id = args["block_id"]
                status = args["status"]
                slot = args["slot"]
                
                status_str = ["NOT_READY", "READY", "QUEUE_FULL", "LOADING"][status]
                print(f"\n✅ [READY_ACK] {cid}: Block {block_id} → {status_str} (Slot {slot})")
                
                # 存儲 ACK
                if cid in self.slaves:
                    self.slaves[cid]["last_ack"][0x3008] = args
                
                # 喚醒等待線程
                if cid in self.ack_queue and 0x3008 in self.ack_queue[cid]:
                    self.ack_queue[cid][0x3008].set()
            
            elif cmd == 0x2004:  # FILE_ACK
                file_id = args["file_id"]
                offset = args["offset"]
                success = args.get("success", 255)
                
                if success == 1:
                    print(f"\n✅ [FILE_ACK] {cid}: Upload Complete")
                elif success == 0:
                    print(f"\n❌ [FILE_ACK] {cid}: Upload Failed")
                
                # 存儲 ACK
                if cid in self.slaves:
                    self.slaves[cid]["last_ack"][0x2004] = args
                
                # 喚醒等待線程
                if cid in self.ack_queue and 0x2004 in self.ack_queue[cid]:
                    self.ack_queue[cid][0x2004].set()
            
            elif cmd == 0x3012:  # BLOCK_COMPLETE
                block_id = args["block_id"]
                start_frame = args["start_frame"]
                end_frame = args["end_frame"]
                actual_fps = args["actual_fps"] / 100.0
                interrupted = args["interrupted"]
                
                status = "INTERRUPTED" if interrupted else "COMPLETE"
                print(f"\n🎬 [BLOCK_{status}] {cid}: Block {block_id} [{start_frame}~{end_frame}] → {actual_fps:.2f} FPS")
                
                # 更新 queue_full 狀態
                if cid in self.slaves:
                    self.slaves[cid]["queue_full"] = False
            
            # 更新最後見到時間
            if cid in self.slaves:
                self.slaves[cid]["last_seen"] = time.time()
            
            return cid
        
        except Exception as e:
            print(f"⚠️ [Dispatch Error] {e}")
            return cid
    
    # ══════════════════════════════════════════════════
    # 發送 API
    # ══════════════════════════════════════════════════
    
    def send_to_targets(self, targets, cmd_id, args):
        """發送指令到目標設備"""
        c_def = self.store.get(cmd_id)
        if not c_def:
            return
        
        # 封裝協議包
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        
        # 封裝 WebSocket Binary Frame
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
        
        if DEBUG_MODE:
            print(f"📤 [SEND] CMD {hex(cmd_id)}: {full_pkt.hex(' ')}")
        
        # 發送到所有目標
        for tid in targets:
            if tid in self.slaves:
                try:
                    self.slaves[tid]["conn"].sendall(full_pkt)
                except:
                    pass
    
    def wait_for_ack(self, slave_id, cmd, timeout=5.0):
        """等待指定指令的 ACK"""
        if slave_id not in self.ack_queue:
            return None
        
        # 清空舊 ACK
        if slave_id in self.slaves:
            self.slaves[slave_id]["last_ack"].pop(cmd, None)
        
        # 創建事件
        event = threading.Event()
        self.ack_queue[slave_id][cmd] = event
        
        # 等待
        if event.wait(timeout):
            # 獲取 ACK 數據
            if slave_id in self.slaves:
                return self.slaves[slave_id]["last_ack"].get(cmd)
        
        return None
    
    # ══════════════════════════════════════════════════
    # 選單功能
    # ══════════════════════════════════════════════════
    
    def select_targets(self):
        """選擇目標設備"""
        ids = list(self.slaves.keys())
        if not ids:
            print("❌ No devices online")
            return []
        
        print("\nOnline Devices:")
        for i, sid in enumerate(ids):
            info = self.slaves[sid]
            print(f"{i+1}. {sid} ({info['addr'][0]})")
        print("a. All")
        
        res = input("👉 Select: ").strip()
        
        if res.lower() == 'a':
            return ids
        
        try:
            return [ids[int(res) - 1]]
        except:
            return []
    
    # ══════════════════════════════════════════════════
    # 文件上傳
    # ══════════════════════════════════════════════════
    
    def upload_file_task(self):
        """文件上傳任務"""
        targets = self.select_targets()
        if not targets:
            return
        
        # 列出可用文件
        files = [f for f in os.listdir('.') if f.endswith(('.bin', '.py', '.json', '.pxld'))]
        if not files:
            print("❌ No files found")
            return
        
        print("\nAvailable Files:")
        for i, f in enumerate(files):
            size = os.path.getsize(f)
            print(f"{i+1}. {f} ({size} bytes)")
        
        try:
            local_name = files[int(input("📂 Choose file: ")) - 1]
        except:
            return
        
        remote_path = input(f"💾 Remote Path [/{local_name}]: ") or f"/{local_name}"
        
        # 讀取文件
        with open(local_name, "rb") as f:
            data = f.read()
        
        # 計算 SHA256
        sha = hashlib.sha256(data).digest()
        
        file_id = 100
        chunk_size = 1024
        
        print(f"\n🚀 Uploading to {len(targets)} device(s)...")
        
        # 發送 FILE_BEGIN
        self.send_to_targets(targets, 0x2001, {
            "file_id": file_id,
            "total_size": len(data),
            "chunk_size": chunk_size,
            "sha256": sha,
            "path": remote_path
        })
        
        # 發送 CHUNK (停等機制)
        for offset in range(0, len(data), chunk_size):
            chunk = data[offset : offset + chunk_size]
            
            for tid in targets:
                if tid not in self.slaves:
                    continue
                
                # 重試機制
                retry = 0
                while retry < 5:
                    self.send_to_targets([tid], 0x2002, {
                        "file_id": file_id,
                        "offset": offset,
                        "data": chunk
                    })
                    
                    # 等待 ACK
                    ack = self.wait_for_ack(tid, 0x2004, timeout=2.0)
                    if ack:
                        break
                    
                    retry += 1
                    print(f"⚠️ [{tid}] Retry {retry}/5 for offset {offset}")
            
            # 顯示進度
            progress = min(offset + chunk_size, len(data))
            print(f"  📤 Progress: {progress}/{len(data)} bytes ({progress * 100 // len(data)}%)", end='\r')
        
        print()  # 換行
        
        # 發送 FILE_END
        self.send_to_targets(targets, 0x2003, {"file_id": file_id})
        
        # 等待最終 ACK
        for tid in targets:
            ack = self.wait_for_ack(tid, 0x2004, timeout=5.0)
            if ack and ack.get("success") == 1:
                print(f"✅ [{tid}] Upload Complete")
            else:
                print(f"❌ [{tid}] Upload Failed")
    
    # ══════════════════════════════════════════════════
    # Stream 控制
    # ══════════════════════════════════════════════════
    
    def stream_menu(self):
        """Stream 控制選單"""
        targets = self.select_targets()
        if not targets:
            return
        
        print("\n--- 🎬 Stream Controller ---")
        print("1. Set Block (Normal Queue)")
        print("2. Set Block (Immediate Jump)")
        print("3. Start Play")
        print("4. Pause / Resume")
        print("5. Stop")
        print("6. Auto Scheduler (推送 N 個 Block)")
        
        c = input("\n👉 Choice: ")
        
        if c == '1':  # Normal Queue
            block_id = int(input("Block ID: "))
            frame_offset = int(input("Frame Offset [0]: ") or "0")
            
            for tid in targets:
                self._set_block(tid, block_id, frame_offset, PRIORITY_QUEUE)
        
        elif c == '2':  # Immediate Jump
            block_id = int(input("Block ID: "))
            frame_offset = int(input("Frame Offset: "))
            
            for tid in targets:
                self._set_block(tid, block_id, frame_offset, PRIORITY_IMMEDIATE)
        
        elif c == '3':  # Play
            self.send_to_targets(targets, 0x300A, {})
            print("🚀 PLAY sent to all targets")
        
        elif c == '4':  # Pause
            pause = int(input("Pause(1) or Resume(0): "))
            self.send_to_targets(targets, 0x3005, {"pause": pause})
        
        elif c == '5':  # Stop
            self.send_to_targets(targets, 0x3002, {})
            print("⏹️ STOP sent to all targets")
        
        elif c == '6':  # Auto Scheduler
            num_blocks = int(input("How many blocks to push: "))
            
            for tid in targets:
                self._auto_scheduler(tid, num_blocks)
    
    def _set_block(self, slave_id, block_id, frame_offset, priority):
        """設置單個 Block"""
        # 發送 STATE_SET
        self.send_to_targets([slave_id], 0x3009, {
            "block_id": block_id,
            "frame_offset": frame_offset,
            "priority": priority,
            "target_slot": 0xFF
        })
        
        # 等待 READY_ACK
        ack = self.wait_for_ack(slave_id, 0x3008, timeout=3.0)
        
        if not ack:
            print(f"❌ [{slave_id}] No response for Block {block_id}")
            return
        
        status = ack["status"]
        
        if status == STATUS_READY:
            print(f"✅ [{slave_id}] Block {block_id} Ready")
        
        elif status == STATUS_NOT_READY:
            # 需要上傳
            print(f"📤 [{slave_id}] Uploading Block {block_id}...")
            
            file_path = f"data_{block_id}.bin"
            if not os.path.exists(file_path):
                print(f"❌ File not found: {file_path}")
                return
            
            # 上傳文件
            self._upload_single_file(slave_id, file_path, f"data_{block_id}.bin")
            
            # 再次發送 STATE_SET (觸發載入)
            self.send_to_targets([slave_id], 0x3009, {
                "block_id": block_id,
                "frame_offset": frame_offset,
                "priority": priority,
                "target_slot": 0xFF
            })
            
            # 等待最終 READY
            final_ack = self.wait_for_ack(slave_id, 0x3008, timeout=3.0)
            if final_ack and final_ack["status"] == STATUS_READY:
                print(f"✅ [{slave_id}] Block {block_id} Loaded")
        
        elif status == STATUS_QUEUE_FULL:
            print(f"⚠️ [{slave_id}] Queue Full")
    
    def _upload_single_file(self, slave_id, local_path, remote_path):
        """上傳單個文件"""
        with open(local_path, "rb") as f:
            data = f.read()
        
        sha = hashlib.sha256(data).digest()
        file_id = 101
        chunk_size = 1024
        
        # FILE_BEGIN
        self.send_to_targets([slave_id], 0x2001, {
            "file_id": file_id,
            "total_size": len(data),
            "chunk_size": chunk_size,
            "sha256": sha,
            "path": remote_path
        })
        
        # FILE_CHUNK
        for offset in range(0, len(data), chunk_size):
            chunk = data[offset : offset + chunk_size]
            
            retry = 0
            while retry < 3:
                self.send_to_targets([slave_id], 0x2002, {
                    "file_id": file_id,
                    "offset": offset,
                    "data": chunk
                })
                
                ack = self.wait_for_ack(slave_id, 0x2004, timeout=1.0)
                if ack:
                    break
                retry += 1
        
        # FILE_END
        self.send_to_targets([slave_id], 0x2003, {"file_id": file_id})
        
        # 等待最終 ACK
        final_ack = self.wait_for_ack(slave_id, 0x2004, timeout=5.0)
        if final_ack and final_ack.get("success") == 1:
            print(f"✅ [{slave_id}] File uploaded")
        else:
            print(f"❌ [{slave_id}] File upload failed")
    
    def _auto_scheduler(self, slave_id, num_blocks):
        """自動推送 N 個 Block"""
        start_block = self.slaves[slave_id].get("next_block", 0)
        
        for i in range(num_blocks):
            block_id = start_block + i
            
            print(f"\n📦 [{slave_id}] Pushing Block {block_id}...")
            
            self._set_block(slave_id, block_id, 0, PRIORITY_QUEUE)
            
            # 檢查 Queue Full
            if self.slaves[slave_id].get("queue_full"):
                print(f"⚠️ [{slave_id}] Queue Full, waiting for BLOCK_COMPLETE...")
                time.sleep(2)  # 等待播完
        
        self.slaves[slave_id]["next_block"] = start_block + num_blocks
    
    # ══════════════════════════════════════════════════
    # 主選單
    # ══════════════════════════════════════════════════
    
    def run(self):
        """主循環"""
        # 啟動 WebSocket Server
        threading.Thread(target=self.start_ws_server, daemon=True).start()
        
        time.sleep(0.5)
        
        while True:
            print(f"\n{'='*60}")
            print(f"🚀 NetBus PC Console | IP: {self.local_ip}")
            print(f"{'='*60}")
            print("1. Discovery Broadcast")
            print("2. Dashboard")
            print("3. Health Check")
            print("4. Upload File")
            print("5. Stream Control")
            print("d. Toggle Debug Mode")
            print("q. Exit")
            
            c = input("\n👉 Choice: ").lower()
            
            if c == '1':
                # Discovery
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                
                p_data = SchemaCodec.encode(self.store.get(0x1001), {
                    "server_ip": self.local_ip,
                    "ws_url": f"ws://{self.local_ip}:8000/ws"
                })
                
                s.sendto(Proto.pack(0x1001, p_data), ('255.255.255.255', 9000))
                s.close()
                
                print("📡 Discovery broadcast sent")
            
            elif c == '2':
                # Dashboard
                print("\n" + "="*85)
                print(f"{'Slave ID':<20} | {'IP':<15} | {'Mem(KB)':<10} | {'Uptime':<10} | {'FPS':<5} | {'Last Seen'}")
                print("="*85)
                
                now = time.time()
                for sid, info in self.slaves.items():
                    mem_kb = info['mem_free'] // 1024
                    uptime_s = info['uptime_ms'] // 1000
                    fps = info.get('render_fps', 0)
                    last_seen = int(now - info['last_seen'])
                    
                    print(f"{sid:<20} | {info['addr'][0]:<15} | {mem_kb:<10} | {uptime_s:<10}s | {fps:<5} | {last_seen}s ago")
                
                print("="*85)
            
            elif c == '3':
                # Health Check
                targets = self.select_targets()
                if targets:
                    self.send_to_targets(targets, 0x1101, {"query_type": 1})
            
            elif c == '4':
                # Upload
                self.upload_file_task()
            
            elif c == '5':
                # Stream
                self.stream_menu()
            
            elif c == 'd':
                # Toggle Debug
                global DEBUG_MODE
                DEBUG_MODE = not DEBUG_MODE
                print(f"🛠️ Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
            
            elif c == 'q':
                # Exit
                self.running = False
                break


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

if __name__ == "__main__":
    tool = PCTestTool()
    try:
        tool.run()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
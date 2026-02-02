"""
PC 端測試工具 (完整修正版)
═══════════════════════════════════════════════════════
修正:
1. dispatch() 中安全訪問所有欄位
2. 添加完整錯誤堆棧打印
3. 處理 i32 負數
"""
import socket
import time
import threading
import os,sys
import hashlib
import struct
import json
import zlib
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) if 'slave' in SCRIPT_DIR else SCRIPT_DIR

os.chdir(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


# 引用 NL3 協議模型
from slave.lib.proto import Proto, StreamParser
from slave.lib.schema_loader import SchemaStore
from slave.lib.schema_codec import SchemaCodec

DEBUG_MODE = True

NO_REPLACEMENT = 0xFFFFFFFF  # 🚀 添加常量定義


class PCTestTool:
    def __init__(self):
        self.store = SchemaStore(dir_path="./schema")
        self.slaves = {}
        self.running = True
        self.local_ip = self.get_local_ip()
    
    def get_local_ip(self):
        """獲取 PC IP"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except:
            return '127.0.0.1'
        finally:
            s.close()
    
    def start_ws_server(self):
        """啟動 WebSocket 服務器"""
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
        
        s.close()
    
    def handle_client(self, conn, addr):
        """處理客戶端連接"""
        curr_id = f"PENDING_{addr[1]}"
        
        try:
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
                raw = conn.recv(8192)  # 🚀 增加接收緩衝
                if not raw:
                    break
                
                if DEBUG_MODE:
                    print(f"📥 [RECV] {len(raw)} bytes")
                
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
            print(f"\n❌ [Conn Error] {curr_id}: {e}")
            traceback.print_exc()
        finally:
            if curr_id in self.slaves:
                del self.slaves[curr_id]
            conn.close()
            print(f"🔌 [Conn] {curr_id} left")
    
    def dispatch(self, cid, cmd, payload):
        """指令分發器 (完整修正版)"""
        try:
            c_def = self.store.get(cmd)
            if not c_def:
                if DEBUG_MODE:
                    print(f"⚠️ Unknown CMD: {hex(cmd)}")
                return cid
            
            try:
                args = SchemaCodec.decode(c_def, payload)
            except Exception as e:
                print(f"❌ [Decode Error] CMD {hex(cmd)}: {e}")
                traceback.print_exc()
                return cid
            
            real_id = None
            
            # HEARTBEAT (0x1201)
            if cmd == 0x1201:
                real_id = args.get("slave_id")
                if cid in self.slaves:
                    self.slaves[cid].update({
                        "mem_free": args.get("mem_free", 0),
                        "uptime": args.get("uptime_ms", 0)
                    })
                
                if DEBUG_MODE:
                    print(f"💓 [Heartbeat] {real_id}")
            
            # STATUS_RSP (0x1102)
            elif cmd == 0x1102:
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
                except Exception as e:
                    print(f"⚠️ Parse status error: {e}")
            
            # FILE_ACK (0x2004)
            elif cmd == 0x2004:
                if cid in self.slaves:
                    self.slaves[cid]["last_ack_off"] = args.get("offset", -1)
                    self.slaves[cid]["ack_event"].set()
            
            # STREAM_READY_ACK (0x3008)
            elif cmd == 0x3008:
                status_map = ["NOT_READY", "READY", "QUEUE_FULL", "LOADING"]
                
                block_id = args.get("block_id", 0)
                status = args.get("status", 0)
                slot = args.get("slot", 255)
                replaced_block = args.get("replaced_block", NO_REPLACEMENT)  # 🚀 使用常量
                slot_type = args.get("slot_type", 0)
                
                status_str = status_map[status] if status < len(status_map) else "UNKNOWN"
                type_str = "Flash" if slot_type == 1 else ("RAM" if slot_type == 2 else "Unknown")
                
                replaced_info = f", Replaced {replaced_block}" if replaced_block != NO_REPLACEMENT else ""
                
                print(f"\n📤 [READY_ACK] Block {block_id} → {status_str} (Slot {slot}, {type_str}){replaced_info}")
            
            # STREAM_BLOCK_COMPLETE (0x3012)
            elif cmd == 0x3012:
                block_id = args.get("block_id", 0)
                start_frame = args.get("start_frame", 0)
                end_frame = args.get("end_frame", 0)
                actual_fps = args.get("actual_fps", 0) / 100.0
                freed_slot = args.get("freed_slot", 255)
                interrupted = args.get("interrupted", 0)
                
                status = "INTERRUPTED" if interrupted else "COMPLETE"
                print(f"\n🏁 [BLOCK_{status}] Block {block_id} [{start_frame}~{end_frame}], FPS {actual_fps:.2f}, Freed Slot {freed_slot}")
            
            # STREAM_STATUS_RSP (0x3015)
            elif cmd == 0x3015:
                try:
                    status_data = json.loads(args["status_json"])
                    print(f"\n📊 [Stream Status]:")
                    print(json.dumps(status_data, indent=2))
                except Exception as e:
                    print(f"⚠️ Parse stream status error: {e}")
            
            # STREAM_ERROR (0x3016)
            elif cmd == 0x3016:
                error_code = args.get("error_code", 0)
                block_id = args.get("block_id", 0)
                slot = args.get("slot", 255)
                message = args.get("message", "")
                print(f"\n❌ [Stream Error] Code {error_code}, Block {block_id}, Slot {slot}: {message}")
            
            # STREAM_PUSH_ACK (0x3018)
            elif cmd == 0x3018:
                block_id = args.get("block_id", 0)
                part_index = args.get("part_index", 0)
                status = args.get("status", 0)
                crc32 = args.get("crc32", 0)
                
                if status == 0:  # OK
                    print(f"✅ [PUSH_ACK] Block {block_id} Part {part_index} OK (CRC32: {crc32:08X})")
                    
                    if cid in self.slaves:
                        self.slaves[cid]["ack_event"].set()
                else:
                    status_str = ["OK", "ERROR", "SIZE_MISMATCH", "CRC_FAIL"][status] if status < 4 else "UNKNOWN"
                    print(f"❌ [PUSH_ACK] Block {block_id} Part {part_index} {status_str}")
            
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
            print(f"⚠️ [Dispatch Error] CMD {hex(cmd) if cmd else 'Unknown'}: {e}")
            traceback.print_exc()
            return cid
    
    def send_to_targets(self, targets, cmd_id, args):
        """發送指令"""
        c_def = self.store.get(cmd_id)
        if not c_def:
            print(f"⚠️ Unknown CMD: {hex(cmd_id)}")
            return
        
        try:
            encoded_payload = SchemaCodec.encode(c_def, args)
            data_pkt = Proto.pack(cmd_id, encoded_payload)
        except Exception as e:
            print(f"❌ [Encode Error] CMD {hex(cmd_id)}: {e}")
            traceback.print_exc()
            return
        
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
        
        if DEBUG_MODE and cmd_id not in [0x1202]:
            print(f"📤 [SEND] CMD {hex(cmd_id)} ({length} bytes)")
        
        for tid in targets:
            if tid in self.slaves:
                try:
                    self.slaves[tid]["conn"].sendall(full_pkt)
                except Exception as e:
                    print(f"❌ [Send Error] {tid}: {e}")
    
    # ══════════════════════════════════════════════════
    # 選單功能 (保持不變)
    # ══════════════════════════════════════════════════
    
    def select_targets(self):
        """選擇目標設備"""
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
        """上傳文件 (Flash 模式)"""
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
        
        time.sleep(0.2)  # 等待 MCU 處理
        
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
        
        print()
        self.send_to_targets(targets, 0x2003, {"file_id": f_id})
        print("✅ Upload Complete")
    
    def stream_config_task(self):
        """配置 Stream"""
        targets = self.select_targets()
        if not targets:
            return
        
        print("\n🔧 Stream Configuration:")
        num_leds = int(input("LED 數量 [2000]: ") or 2000)
        f_per_block = int(input("每 Block 幀數 [50]: ") or 50)
        total_blocks = int(input("總 Block 數 [100]: ") or 100)
        fps = int(input("FPS [40]: ") or 40)
        mode = int(input("預設模式 (0=Flash, 1=RAM, 2=智能) [2]: ") or 2)
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
        """設置播放目標"""
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
        """播放"""
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x300A, {})
        print("▶️ PLAY Sent")
    
    def stream_pause_task(self):
        """暫停/恢復"""
        targets = self.select_targets()
        if not targets:
            return
        
        pause = int(input("Pause (0=Resume, 1=Pause): ") or 0)
        
        self.send_to_targets(targets, 0x3005, {"pause": pause})
        print(f"⏸️ {'PAUSE' if pause else 'RESUME'} Sent")
    
    def stream_stop_task(self):
        """停止"""
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x3002, {})
        print("⏹️ STOP Sent")
    
    def stream_abort_task(self):
        """立即中斷"""
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x3010, {})
        print("🛑 ABORT Sent")
    
    def stream_status_task(self):
        """查詢狀態"""
        targets = self.select_targets()
        if not targets:
            return
        
        self.send_to_targets(targets, 0x3014, {})
        print("📊 Status Query Sent")
    
    def stream_push_task(self):
        """推送 Block 到 RAM 模式"""
        targets = self.select_targets()
        if not targets:
            return
        
        files = [f for f in os.listdir('.') if f.endswith('.bin')]
        if not files:
            print("❌ No .bin files found")
            return
        
        print("\nAvailable Files:")
        for i, f in enumerate(files):
            size = os.path.getsize(f)
            print(f"{i+1}. {f} ({size} bytes, {size // 1024} KB)")
        
        try:
            local_name = files[int(input("📂 Choose file: "))-1]
        except:
            return
        
        with open(local_name, "rb") as f:
            data = f.read()
        
        block_id = int(input("Block ID: "))
        num_leds = int(input("Num LEDs [100]: ") or 100)
        f_per_part = int(input("Frames per part [50]: ") or 50)
        
        bytes_per_part = num_leds * f_per_part * 4
        
        if len(data) % bytes_per_part != 0:
            print(f"⚠️ File size {len(data)} not divisible by {bytes_per_part}")
            data = data[:len(data) - (len(data) % bytes_per_part)]
        
        total_parts = len(data) // bytes_per_part
        
        print(f"\n🚀 Pushing Block {block_id} to {targets}...")
        print(f"   Total Size: {len(data)} bytes ({len(data) // 1024} KB)")
        print(f"   Parts: {total_parts}")
        print(f"   Part Size: {bytes_per_part} bytes ({bytes_per_part // 1024} KB)")
        
        crc32_expect = zlib.crc32(data) & 0xFFFFFFFF
        print(f"   Expected CRC32: {crc32_expect:08X}")
        
        for part_index in range(total_parts):
            offset = part_index * bytes_per_part
            part_data = data[offset : offset + bytes_per_part]
            
            print(f"\n📤 Pushing Part {part_index}/{total_parts-1}...")
            
            for tid in targets:
                if tid not in self.slaves:
                    continue
                
                retry = 0
                while retry < 3:
                    self.slaves[tid]["ack_event"].clear()
                    
                    self.send_to_targets([tid], 0x3017, {
                        "block_id": block_id,
                        "part_index": part_index,
                        "data": part_data
                    })
                    
                    if self.slaves[tid]["ack_event"].wait(timeout=3.0):
                        break
                    
                    retry += 1
                    print(f"⚠️ [{tid}] Retry {retry}/3 for part {part_index}")
                
                if retry >= 3:
                    print(f"❌ [{tid}] Failed to push part {part_index}")
                    return
            
            print(f"✅ Part {part_index} sent")
        
        print(f"\n✅ All parts pushed!")
        print(f"📊 Please verify CRC32 matches: {crc32_expect:08X}")
    
    def run(self):
        """主入口"""
        threading.Thread(target=self.start_ws_server, daemon=True).start()
        
        while True:
            print(f"\n{'='*60}")
            print(f"🚀 NetBus PC Console ({self.local_ip})")
            print(f"{'='*60}")
            print("1. Broadcast Discovery")
            print("2. Dashboard")
            print("3. Upload File (Flash)")
            print("4. Stream Config")
            print("5. Stream State Set")
            print("6. Stream Play")
            print("7. Stream Pause/Resume")
            print("8. Stream Stop")
            print("9. Stream Push (RAM)")
            print("a. Stream Abort")
            print("s. Stream Status Query")
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
                print("\n" + "=" * 80)
                print(f"{'Slave ID':<20} | {'IP':<15} | {'FreeMem':<10} | {'Uptime':<10}")
                print("=" * 80)
                now = time.time()
                for sid, info in self.slaves.items():
                    uptime_s = info['uptime'] // 1000
                    last_seen = int(now - info['last_seen'])
                    print(f"{sid:<20} | {info['addr'][0]:<15} | {info['mem_free']:<10} | {uptime_s:<10}s (Last: {last_seen}s ago)")
                print("=" * 80)
            
            elif c == '3':
                self.upload_file_task()
            
            elif c == '4':
                self.stream_config_task()
            
            elif c == '5':
                self.stream_state_set_task()
            
            elif c == '6':
                self.stream_play_task()
            
            elif c == '7':
                self.stream_pause_task()
            
            elif c == '8':
                self.stream_stop_task()
            
            elif c == '9':
                self.stream_push_task()
            
            elif c == 'a':
                self.stream_abort_task()
            
            elif c == 's':
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
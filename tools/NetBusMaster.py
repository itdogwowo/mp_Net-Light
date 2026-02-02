import socket
import time
import threading
import os,sys
import hashlib
import struct
import json
from pathlib import Path
from pygame import mixer  # 用於播放同步音訊


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR) if 'slave' in SCRIPT_DIR else SCRIPT_DIR

os.chdir(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# 核心協議庫
try:
    from slave.lib.proto import Proto, StreamParser
    from slave.lib.schema_loader import SchemaStore
    from slave.lib.schema_codec import SchemaCodec
    from PXLDv3Splitter import PXLDv3Decoder 
except ImportError as e:
    print(f"❌ 導入錯誤: {e}")

class NetBusMaster:
    def __init__(self, config_file="slave_map.json"):
        self.store = SchemaStore(dir_path="./schema")
        self.slaves = {}      # { cid: {conn, addr, ack_event, query_res} }
        self.running = True
        self.local_ip = self.get_local_ip()
        
        # 自動化配置
        self.config_file = config_file
        self.config = self.load_config()
        self.selected_targets = []  
        self.prepared_data = {}     # {play_id: bytearray}
        
        mixer.init()
        threading.Thread(target=self.start_ws_server, daemon=True).start()

    # ==================== 配置管理 ====================
    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"mp3_file": "bgm.mp3", "sync_delay_ms": 150, "mapping": {}}

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    # ==================== 通訊核心 ====================
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
        s.listen(20)
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except: break

    def handle_client(self, conn, addr):
        cid = f"PENDING_{addr[1]}"
        try:
            # --- 1. WebSocket 握手 & 從 Path 提取 ID ---
            header_data = conn.recv(1024).decode()
            if not header_data or "Upgrade: websocket" not in header_data:
                conn.close(); return

            first_line = header_data.split('\r\n')[0]
            parts = first_line.split(' ')
            if len(parts) >= 2:
                path = parts[1].strip('/')
                if path and path != 'ws': cid = path
            
            resp = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    "Connection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
            conn.send(resp.encode())
            
            # --- 2. 註冊與自動分配 PlayID ---
            if cid not in self.config["mapping"]:
                pids = [v["play_id"] for v in self.config["mapping"].values() if "play_id" in v]
                new_pid = max(pids) + 1 if pids else 0
                self.config["mapping"][cid] = {"play_id": new_pid, "last_sha": ""}
                self.save_config()
                print(f"🆕 [New Device] MAC: {cid} -> PlayID: {new_pid}")
            else:
                print(f"🆔 [Device-In] MAC: {cid} (PlayID: {self.config['mapping'][cid]['play_id']})")

            self.slaves[cid] = {
                "conn": conn, "addr": addr, "parser": StreamParser(),
                "ack_event": threading.Event(), "query_event": threading.Event(),
                "remote_sha": None
            }
            
            p = self.slaves[cid]["parser"]
            while self.running:
                raw = conn.recv(4096)
                if not raw: break
                
                # WebSocket Binary 解包
                if raw[0] == 0x82:
                    plen = raw[1] & 0x7F
                    off = 2
                    if plen == 126: off = 4
                    elif plen == 127: off = 10
                    p.feed(raw[off:])
                else: p.feed(raw)

                for ver, addr_pkt, cmd, payload in p.pop():
                    cid = self.dispatch_logic(cid, cmd, payload)
        except: pass
        finally:
            if cid in self.slaves: del self.slaves[cid]
            conn.close()

    def dispatch_logic(self, cid, cmd, payload):
        c_def = self.store.get(cmd)
        args = SchemaCodec.decode(c_def, payload)

        if cmd == 0x1102:
            try:
                status_data = json.loads(args["status_json"])
                # 💡 這裡是 MCU 主動發送的健康包
                # 我們可以從這裡提取 render_fps 或 current_frame
                print(f"\r📉 [Status] {cid} -> Render FPS: {status_data.get('render_fps', 0)} | Msg: {status_data.get('msg', '')}", end="")
                
                # 如果你想看累計值，可以在 self.slaves 紀錄
                if cid in self.slaves:
                    self.slaves[cid]["current_fps"] = status_data.get('render_fps', 0)
            except:
                pass

        # STREAM_BLOCK_COMPLETE (0x3012) - 當一個 Block 播完時的效能總結
        elif cmd == 0x3012:
            block_id = args.get("block_id", 0)
            start_f = args.get("start_frame", 0)
            end_f = args.get("end_frame", 0)
            actual_fps = args.get("actual_fps", 0) / 100.0  # i32 定點數轉換
            
            # 計算該 Block 總共跑了多少影格
            frame_count = end_f - start_f
            
            print(f"\n📊 [Perf Report] Slave: {cid}")
            print(f"   ﹂ Block ID: {block_id}")
            print(f"   ﹂ Frame Range: {start_f} ~ {end_f} (Total: {frame_count} frames)")
            print(f"   ﹂ Realtime Performance: {actual_fps:.2f} FPS")
            print("-" * 35)


        
        if cmd == 0x2004: # FILE_ACK
            self.slaves[cid]["ack_event"].set()
        elif cmd == 0x2006: # FILE_QUERY_RSP
            self.slaves[cid]["remote_sha"] = args["sha256"]
            self.slaves[cid]["query_event"].set()
        elif cmd == 0x1102: # 狀態回報識別
            real_id = json.loads(args["status_json"]).get("id")
            if real_id and real_id != cid:
                self.slaves[real_id] = self.slaves.pop(cid)
                cid = real_id
        return cid

    def send_pkt(self, targets, cmd_id, args):
        c_def = self.store.get(cmd_id)
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        l = len(data_pkt)
        
        # WS Header
        hdr = bytearray([0x82])
        if l <= 125: hdr.append(l)
        elif l <= 65535: hdr.append(126); hdr.extend(struct.pack(">H", l))
        else: hdr.append(127); hdr.extend(struct.pack(">Q", l))
        
        pkt = hdr + data_pkt
        for tid in targets:
            if tid in self.slaves:
                try: self.slaves[tid]["conn"].sendall(pkt)
                except: pass

    # ==================== 工作流 ====================
    
    def step_1_select_slaves(self):
        print("\n[Step 1] 掃描網絡中...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        p_data = SchemaCodec.encode(self.store.get(0x1001), {"server_ip": self.local_ip, "ws_url": f"ws://{self.local_ip}:8000"})
        s.sendto(Proto.pack(0x1001, p_data), ('255.255.255.255', 9000)); s.close()
        
        time.sleep(1.0)
        ids = list(self.slaves.keys())
        if not ids: print("❌ 未發現設備"); return
        
        print("\n--- 在線列表 ---")
        for i, sid in enumerate(ids):
            pid = self.config["mapping"].get(sid, {}).get("play_id", "?")
            print(f"{i+1}. {sid} (PlayID: {pid})")
        
        choice = input("\n👉 目標 (a/數字): ").lower()
        self.selected_targets = ids if choice == 'a' else [ids[int(x)-1] for x in choice.split(',')]
        print(f"✅ 已選中 {len(self.selected_targets)} 個設備")

    def step_2_prepare_data(self):
        if not self.selected_targets: return
        path = input("\n[Step 2] .pxld 路徑: ").strip()
        if not os.path.exists(path): return

        print("⚙️ 分片中...")
        self.prepared_data.clear()
        with PXLDv3Decoder(path) as decoder:
            needed_pids = {self.config["mapping"][tid]["play_id"] for tid in self.selected_targets}
            for pid in needed_pids:
                print(f"  📦 提取 PlayID: {pid}...", end="", flush=True)
                data = bytearray()
                for frame in decoder.iterate_frames():
                    data.extend(decoder.get_slave_data(frame, pid))
                self.prepared_data[pid] = data
                print(f" OK ({len(data)//1024} KB)")
        print("✅ 分片完成")

    def step_3_deploy(self):
        if not self.prepared_data: return
        print("\n[Step 3] 執行智能部署...")
        for tid in self.selected_targets:
            pid = self.config["mapping"][tid].get("play_id")
            data = self.prepared_data.get(pid)
            if not data: continue
            
            local_sha = hashlib.sha256(data).digest()
            
            # --- 智能檢查 0x2005 ---
            print(f"🧐 檢查 {tid}...", end="", flush=True)
            self.slaves[tid]["query_event"].clear()
            self.send_pkt([tid], 0x2005, {"path": "/data.bin"})
            
            if self.slaves[tid]["query_event"].wait(timeout=120.0):
                if self.slaves[tid]["remote_sha"].hex() == local_sha.hex():
                    print(" ✨ 一致, 跳過")
                    self.config["mapping"][tid]["last_sha"] = local_sha.hex()
                    continue
            print(" 🆙 變動, 開始同步")
            
            # 上傳流
            self.send_pkt([tid], 0x2001, {"file_id":1, "total_size":len(data), "chunk_size":1024, "sha256":local_sha, "path":"/data.bin"})
            for off in range(0, len(data), 1024):
                chunk = data[off : off+1024]
                self.slaves[tid]["ack_event"].clear()
                self.send_pkt([tid], 0x2002, {"file_id":1, "offset":off, "data":chunk})
                if not self.slaves[tid]["ack_event"].wait(timeout=60.0):
                    print(f"❌ {tid} ACK 超時")
                    break
            self.send_pkt([tid], 0x2003, {"file_id":1})
            self.config["mapping"][tid]["last_sha"] = local_sha.hex()
            self.save_config()
        print("✅ 部署完畢")

    def step_4_sync_play(self):
        if not self.selected_targets: return
        print("\n[Step 4] s:播放 | q:停止")
        cmd = input("👉: ").lower()
        if cmd == 's':
            self.send_pkt(self.selected_targets, 0x3009, {"file_name":"data.bin", "block_id":0, "play_mode":1})
            time.sleep(0.5)
            if os.path.exists(self.config["mp3_file"]):
                mixer.music.load(self.config["mp3_file"])
                mixer.music.play()
            wait = self.config["sync_delay_ms"] / 1000.0
            if wait > 0: time.sleep(wait)
            self.send_pkt(self.selected_targets, 0x300A, {}) 
        elif cmd == 'q':
            self.send_pkt(self.selected_targets, 0x3002, {})
            mixer.music.stop()

    def main_loop(self):
        while self.running:
            print("\n" + "="*40 + "\n NetBus Master 工作站\n" + "="*40)
            print(" 1.Select | 2.Slice | 3.Deploy | 4.SyncPlay | q.Exit")
            ch = input("\n👉: ").lower()
            if ch == '1': self.step_1_select_slaves()
            elif ch == '2': self.step_2_prepare_data()
            elif ch == '3': self.step_3_deploy()
            elif ch == '4': self.step_4_sync_play()
            elif ch == 'q': break

if __name__ == "__main__":
    app = NetBusMaster()
    app.main_loop()
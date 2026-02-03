import socket
import time
import threading
import os,sys
import hashlib
import struct
import json
from pathlib import Path

# 模式切換：'miniaudio' 或 'pygame'
AUDIO_MODE = 'miniaudio' 

try:
    import miniaudio
except ImportError:
    AUDIO_MODE = 'pygame'  # 如果沒裝 miniaudio，自動回退

try:
    from pygame import mixer
except ImportError:
    pass


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.chdir(SCRIPT_DIR)
print(PROJECT_ROOT)
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
        self.store = SchemaStore(dir_path=f"{PROJECT_ROOT}/slave/schema")
        self.slaves = {}      # { cid: {conn, addr, ack_event, query_res} }
        self.running = True
        self.local_ip = self.get_local_ip()

        self.is_playing = False  # 新增：控制音訊播放開關
        
        # 自動化配置
        self.config_file = config_file
        self.config = self.load_config()
        self.selected_targets = []  
        self.prepared_data = {}     # {play_id: bytearray}
        
        threading.Thread(target=self.start_ws_server, daemon=True).start()

    # ==================== 配置管理 ====================
    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"sync_delay_ms": 150, "mapping": {}}

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
        if not self.selected_targets: 
            print("⚠️ 請先執行 Step 1 選擇設備")
            return
            
        # --- 自動掃描目錄下的 .pxld 檔案 ---
        pxld_files = [f for f in os.listdir('.') if f.endswith('.pxld')]
        if not pxld_files:
            print("❌ 目錄下找不到任何 .pxld 檔案")
            return
        
        print("\n📂 [Step 2] 選擇動畫數據源:")
        for i, f in enumerate(pxld_files):
            print(f"  {i+1}. {f}")
            
        try:
            choice = int(input("👉 請選擇編號: ")) - 1
            if choice < 0 or choice >= len(pxld_files): raise ValueError
            path = pxld_files[choice]
        except:
            print("❌ 選擇無效"); return

        print(f"⚙️ 正在切分動畫: {path}...")
        self.prepared_data.clear()
        
        # 內存優化：使用上下文管理器確保資源釋放
        with PXLDv3Decoder(path) as decoder:
            needed_pids = {self.config["mapping"][tid].get("play_id") for tid in self.selected_targets}
            for pid in needed_pids:
                if pid is None: continue
                print(f"  📦 提取 PlayID: {pid}...", end="", flush=True)
                data = bytearray()
                for frame in decoder.iterate_frames():
                    data.extend(decoder.get_slave_data(frame, pid))
                self.prepared_data[pid] = data
                print(f" OK ({len(data)//1024} KB)")
        print("✅ 動畫分片完成")

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
        """
        [完整版] 同步播放控制器
        支援正負延遲校準、雙引擎切換，以及「按鍵即播」觸發機制
        """
        if not self.selected_targets: 
            print("⚠️ 未選擇設備，請先執行 Step 1"); return

        # --- 1. 自動文件選擇 (MP3) ---
        mp3_files = [f for f in os.listdir('.') if f.endswith('.mp3')]
        if not mp3_files:
            print("❌ 當前目錄下找不到 MP3 文件")
            return
        
        print(f"\n🎵 [音訊準備] 模式: {AUDIO_MODE}")
        for i, f in enumerate(mp3_files):
            print(f"  {i+1}. {f} ({os.path.getsize(f)//1024} KB)")
        
        try:
            choice_idx = int(input("👉 請選擇 MP3 編號 (輸入 0 取消): ")) - 1
            if choice_idx < 0: return
            selected_mp3 = mp3_files[choice_idx]
        except (ValueError, IndexError):
            print("❌ 選擇無效"); return

        # --- 2. 預備 Slave (加載與緩衝) ---
        print(f"⚙️ 正在通知 Slave 預備數據...")
        # 通知所有 Slave 開啟 data.bin 並進入待命狀態
        self.send_pkt(self.selected_targets, 0x3009, {
            "file_name": "data.bin", 
            "block_id": 0, 
            "play_mode": 1
        })
        time.sleep(0.5) # 給予緩衝，確保 Slave 磁碟 IO 完成

        # --- 3. 等待用戶最終擊發指令 ---
        print("\n" + "!"*40)
        print("     所有系統就緒，等待擊發指令")
        print(f"     當前延遲設定: {self.config.get('sync_delay_ms', 0)} ms")
        print("     輸入 'go' 開始播放 | 輸入 'q' 取消預備")
        print("!"*40)

        trigger = input("🚀 指令: ").lower()
        if trigger != 'go':
            print("🛑 播放已取消")
            return

        # --- 4. 核心同步執行 (處理正負延遲) ---
        delay_ms = self.config.get("sync_delay_ms", 150)
        delay_sec = abs(delay_ms) / 1000.0

        if delay_ms >= 0:
            # ✅ 正值：電腦先播，後發脈衝 (適用於補償音效卡啟動延遲)
            self._start_audio_stream(selected_mp3)
            if delay_ms > 0:
                # 這裡不需要加 time.sleep，因為 _start_audio_stream 是非阻塞的
                # 我們直接在主線程 sleep 完後發送脈衝
                time.sleep(delay_sec)
            self.send_pkt(self.selected_targets, 0x300A, {}) 
            print("🔥 [SYNC] 音訊啟動 -> 延遲脈衝已發送")
        else:
            # ✅ 負值：先發脈衝，電腦稍後啟動 (適用於補償 MCU 解碼延遲)
            self.send_pkt(self.selected_targets, 0x300A, {})
            print(f"🚀 [SYNC] 脈衝已先發 -> 電腦等待 {abs(delay_ms)}ms...")
            time.sleep(delay_sec)
            self._start_audio_stream(selected_mp3)
            print("🔥 [SYNC] 音訊已補償啟動")

    def _start_audio_stream(self, file_path):
        self.is_playing = True # 標記開始播放
        
        def _play_task():
            try:
                if AUDIO_MODE == 'miniaudio':
                    with miniaudio.PlaybackDevice() as device:
                        stream = miniaudio.stream_file(file_path)
                        device.start(stream)
                        # --- 核心停止判斷 ---
                        while device.is_active and self.running and self.is_playing:
                            time.sleep(0.1)
                        device.stop() # 停止設備
                else:
                    if not mixer.get_init(): mixer.init()
                    mixer.music.load(file_path)
                    mixer.music.play()
                    # --- 核心停止判斷 ---
                    while mixer.music.get_busy() and self.running and self.is_playing:
                        time.sleep(0.1)
                    mixer.music.stop() # 停止音樂
            except Exception as e:
                print(f"\n[Audio Error] {e}")
            finally:
                self.is_playing = False # 播放結束或被停止後重置狀態

        threading.Thread(target=_play_task, daemon=True).start()

    def stop_all(self):
        """
        同時停止本地音訊與所有遠端設備
        """
        print("\n🛑 執行全局停止...")
        self.is_playing = False # 讓播放線程跳出循環
        
        # 發送網路停止指令 (根據你的協議，0x3002 通常是停止)
        if self.selected_targets:
            self.send_pkt(self.selected_targets, 0x3002, {})
        
        # 如果是 Pygame 模式，額外確保停止（避免線程反應延遲）
        if AUDIO_MODE == 'pygame':
            try:
                if mixer.get_init(): mixer.music.stop()
            except: pass
        
        print("✅ 已發送停止信號")

    def main_loop(self):
        while self.running:
            print("\n" + "="*40)
            print(" 1.Select | 2.Slice | 3.Deploy | 4.SyncPlay")
            print(" s.STOP ALL | q.Exit") # 這裡增加一個快捷停止鍵
            print("="*40)
            
            ch = input("\n👉: ").lower()
            if ch == '1': self.step_1_select_slaves()
            elif ch == '2': self.step_2_prepare_data()
            elif ch == '3': self.step_3_deploy()
            elif ch == '4': self.step_4_sync_play()
            elif ch == 's': self.stop_all() # 這裡調用停止
            elif ch == 'q': 
                self.stop_all()
                self.running = False
                break
if __name__ == "__main__":
    app = NetBusMaster()
    app.main_loop()
    
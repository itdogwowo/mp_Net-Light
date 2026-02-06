import socket
import time
import threading
import os, sys
import hashlib
import struct
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from collections import defaultdict

# 模式切換：'miniaudio' 或 'pygame'
AUDIO_MODE = 'miniaudio' 

try:
    import miniaudio
except ImportError:
    AUDIO_MODE = 'pygame'
    
try:
    from pygame import mixer
except ImportError:
    pass

print(AUDIO_MODE)

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
    from tools.PXLDv3Splitter import PXLDv3Decoder 
except ImportError as e:
    print(f"❌ 導入錯誤: {e}")


class DeviceMonitor:
    """
    設備實時監控數據模型
    """
    def __init__(self, device_id):
        self.device_id = device_id
        self.play_id = None
        self.status = "離線"  # 離線/待機/傳輸中/播放中/錯誤
        
        # 傳輸進度
        self.upload_progress = 0.0  # 0-100
        self.upload_speed = 0.0     # KB/s
        self.uploaded_bytes = 0
        self.total_bytes = 0
        
        # 性能指標
        self.render_fps = 0.0
        self.current_frame = 0
        self.total_frames = 0
        
        # 統計數據
        self.block_count = 0
        self.avg_fps = 0.0
        self.last_update = time.time()
        self.error_msg = ""


class ConsoleUI:
    """
    專業終端UI渲染引擎
    使用 ANSI 轉義序列實現無閃爍刷新
    """
    
    @staticmethod
    def clear_screen():
        """清屏"""
        print("\033[2J\033[H", end="")
    
    @staticmethod
    def move_cursor(row, col):
        """移動光標"""
        print(f"\033[{row};{col}H", end="")
    
    @staticmethod
    def hide_cursor():
        """隱藏光標"""
        print("\033[?25l", end="")
    
    @staticmethod
    def show_cursor():
        """顯示光標"""
        print("\033[?25h", end="")
    
    @staticmethod
    def get_color(value, threshold_good=80, threshold_warn=50):
        """
        根據數值返回顏色碼
        綠色 >= threshold_good
        黃色 >= threshold_warn
        紅色 < threshold_warn
        """
        if value >= threshold_good:
            return "\033[92m"  # 亮綠
        elif value >= threshold_warn:
            return "\033[93m"  # 亮黃
        else:
            return "\033[91m"  # 亮紅
    
    @staticmethod
    def reset_color():
        return "\033[0m"
    
    @staticmethod
    def draw_progress_bar(percent, width=30):
        """
        繪製進度條
        █████████░░░░░░░ 60%
        """
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        color = ConsoleUI.get_color(percent)
        return f"{color}{bar}{ConsoleUI.reset_color()} {percent:5.1f}%"


class MonitorPanel:
    """
    監控面板核心
    """
    def __init__(self):
        self.monitors = {}  # {device_id: DeviceMonitor}
        self.lock = threading.Lock()
        self.running = False
        self.refresh_rate = 0.1  # 100ms 刷新一次
        self.render_thread = None
        
    def register_device(self, device_id, play_id=None):
        """註冊新設備"""
        with self.lock:
            if device_id not in self.monitors:
                monitor = DeviceMonitor(device_id)
                monitor.play_id = play_id
                monitor.status = "待機"
                self.monitors[device_id] = monitor
    
    def update_device(self, device_id, **kwargs):
        """更新設備狀態"""
        with self.lock:
            if device_id in self.monitors:
                monitor = self.monitors[device_id]
                for key, value in kwargs.items():
                    if hasattr(monitor, key):
                        setattr(monitor, key, value)
                monitor.last_update = time.time()
    
    def remove_device(self, device_id):
        """移除設備"""
        with self.lock:
            if device_id in self.monitors:
                self.monitors[device_id].status = "離線"
    
    def start(self):
        """啟動面板渲染"""
        if not self.running:
            self.running = True
            ConsoleUI.hide_cursor()
            ConsoleUI.clear_screen()
            self.render_thread = threading.Thread(target=self._render_loop, daemon=True)
            self.render_thread.start()
    
    def stop(self):
        """停止面板"""
        self.running = False
        if self.render_thread:
            self.render_thread.join(timeout=1.0)
        ConsoleUI.show_cursor()
    
    def _render_loop(self):
        """渲染循環"""
        while self.running:
            self._render_frame()
            time.sleep(self.refresh_rate)
    
    def _render_frame(self):
        """渲染一幀畫面"""
        with self.lock:
            ConsoleUI.move_cursor(1, 1)
            
            # 標題欄
            title = f"╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗"
            subtitle = f"║  🎬 NetBus Master 實時監控面板  │  設備數: {len(self.monitors)}  │  更新時間: {datetime.now().strftime('%H:%M:%S')}           ║"
            divider = f"╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣"
            
            print(title)
            print(subtitle)
            print(divider)
            
            # 設備列表
            if not self.monitors:
                print("║  [無設備]                                                                                            ║")
            else:
                for device_id, monitor in sorted(self.monitors.items()):
                    self._render_device_row(monitor)
            
            # 底部欄
            bottom = f"╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝"
            print(bottom)
            print()  # 留一行給用戶輸入
    
    def _render_device_row(self, monitor: DeviceMonitor):
        """渲染單個設備行"""
        # 設備ID (截斷過長ID)
        device_str = f"{monitor.device_id[:12]:<12}"
        
        # PlayID
        play_id_str = f"P{monitor.play_id:02d}" if monitor.play_id is not None else "---"
        
        # 狀態顏色
        status_colors = {
            "離線": "\033[90m",    # 灰色
            "待機": "\033[96m",    # 青色
            "傳輸中": "\033[93m",  # 黃色
            "播放中": "\033[92m",  # 綠色
            "錯誤": "\033[91m"     # 紅色
        }
        status_color = status_colors.get(monitor.status, "\033[0m")
        status_str = f"{status_color}{monitor.status:<6}{ConsoleUI.reset_color()}"
        
        # 根據狀態顯示不同信息
        if monitor.status == "傳輸中":
            # 顯示上傳進度
            progress_bar = ConsoleUI.draw_progress_bar(monitor.upload_progress, width=20)
            speed_str = f"{monitor.upload_speed:>6.1f} KB/s"
            info = f"{progress_bar} │ {speed_str}"
            
        elif monitor.status == "播放中":
            # 顯示播放進度和FPS
            play_progress = (monitor.current_frame / monitor.total_frames * 100) if monitor.total_frames > 0 else 0
            fps_color = ConsoleUI.get_color(monitor.render_fps, threshold_good=25, threshold_warn=15)
            fps_str = f"{fps_color}{monitor.render_fps:>5.1f} FPS{ConsoleUI.reset_color()}"
            frame_str = f"{monitor.current_frame}/{monitor.total_frames}"
            info = f"Frame: {frame_str:<12} │ {fps_str} │ Blocks: {monitor.block_count}"
            
        elif monitor.status == "錯誤":
            info = f"\033[91m{monitor.error_msg[:50]}\033[0m"
            
        else:
            # 待機/離線狀態
            idle_time = int(time.time() - monitor.last_update)
            info = f"閒置 {idle_time}s"
        
        # 組合輸出
        line = f"║ {device_str} │ {play_id_str} │ {status_str} │ {info:<58} ║"
        # 確保行長度一致 (處理ANSI碼導致的長度問題)
        print(line)


class NetBusMaster:
    def __init__(self, config_file="slave_map.json"):
        self.store = SchemaStore(dir_path=f"{PROJECT_ROOT}/slave/schema")
        self.slaves = {}
        self.running = True
        self.local_ip = self.get_local_ip()
        self.is_playing = False
        
        # 監控面板
        self.panel = MonitorPanel()
        
        # 配置管理
        self.config_file = config_file
        self.config = self.load_config()
        self.selected_targets = []
        self.prepared_data = {}
        
        # 部署統計
        self.deploy_stats = defaultdict(lambda: {"start_time": 0, "bytes_sent": 0})
        
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
        except:
            return '127.0.0.1'
        finally:
            s.close()
    
    def start_ws_server(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 8000))
        s.listen(20)
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except:
                break
    
    def handle_client(self, conn, addr):
        cid = f"PENDING_{addr[1]}"
        try:
            # WebSocket 握手
            header_data = conn.recv(1024).decode()
            if not header_data or "Upgrade: websocket" not in header_data:
                conn.close()
                return
            
            first_line = header_data.split('\r\n')[0]
            parts = first_line.split(' ')
            if len(parts) >= 2:
                path = parts[1].strip('/')
                if path and path != 'ws':
                    cid = path
            
            resp = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    "Connection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
            conn.send(resp.encode())
            
            # 註冊設備
            if cid not in self.config["mapping"]:
                pids = [v["play_id"] for v in self.config["mapping"].values() if "play_id" in v]
                new_pid = max(pids) + 1 if pids else 0
                self.config["mapping"][cid] = {"play_id": new_pid, "last_sha": ""}
                self.save_config()
            
            play_id = self.config["mapping"][cid]["play_id"]
            self.panel.register_device(cid, play_id)
            
            self.slaves[cid] = {
                "conn": conn, "addr": addr, "parser": StreamParser(),
                "ack_event": threading.Event(), "query_event": threading.Event(),
                "remote_sha": None
            }
            
            p = self.slaves[cid]["parser"]
            while self.running:
                raw = conn.recv(4096)
                if not raw:
                    break
                
                # WebSocket 解包
                if raw[0] == 0x82:
                    plen = raw[1] & 0x7F
                    off = 2
                    if plen == 126:
                        off = 4
                    elif plen == 127:
                        off = 10
                    p.feed(raw[off:])
                else:
                    p.feed(raw)
                
                for ver, addr_pkt, cmd, payload in p.pop():
                    cid = self.dispatch_logic(cid, cmd, payload)
        
        except Exception as e:
            self.panel.update_device(cid, status="錯誤", error_msg=str(e))
        finally:
            if cid in self.slaves:
                del self.slaves[cid]
            self.panel.remove_device(cid)
            conn.close()
    
    def dispatch_logic(self, cid, cmd, payload):
        c_def = self.store.get(cmd)
        args = SchemaCodec.decode(c_def, payload)
        
        # 狀態心跳 (0x1102)
        if cmd == 0x1102:
            try:
                status_data = json.loads(args["status_json"])
                render_fps = status_data.get('render_fps', 0)
                current_frame = status_data.get('current_frame', 0)
                
                # 更新面板
                self.panel.update_device(
                    cid,
                    render_fps=render_fps,
                    current_frame=current_frame
                )
                
            except Exception as e:
                pass
        
        # Block 完成報告 (0x3012)
        elif cmd == 0x3012:
            block_id = args.get("block_id", 0)
            start_f = args.get("start_frame", 0)
            end_f = args.get("end_frame", 0)
            actual_fps = args.get("actual_fps", 0) / 100.0
            
            # 更新統計
            if cid in self.panel.monitors:
                monitor = self.panel.monitors[cid]
                monitor.block_count += 1
                # 計算移動平均FPS
                monitor.avg_fps = (monitor.avg_fps * (monitor.block_count - 1) + actual_fps) / monitor.block_count
        
        # 文件ACK (0x2004)
        elif cmd == 0x2004:
            if cid in self.slaves:
                self.slaves[cid]["ack_event"].set()
        
        # 文件查詢響應 (0x2006)
        elif cmd == 0x2006:
            if cid in self.slaves:
                self.slaves[cid]["remote_sha"] = args["sha256"]
                self.slaves[cid]["query_event"].set()
        
        # 設備ID識別
        elif cmd == 0x1102:
            real_id = json.loads(args["status_json"]).get("id")
            if real_id and real_id != cid:
                # 轉移監控數據
                if cid in self.panel.monitors:
                    self.panel.monitors[real_id] = self.panel.monitors.pop(cid)
                    self.panel.monitors[real_id].device_id = real_id
                
                self.slaves[real_id] = self.slaves.pop(cid)
                cid = real_id
        
        return cid
    
    def send_pkt(self, targets, cmd_id, args):
        c_def = self.store.get(cmd_id)
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        l = len(data_pkt)
        
        # WS Header
        hdr = bytearray([0x82])
        if l <= 125:
            hdr.append(l)
        elif l <= 65535:
            hdr.append(126)
            hdr.extend(struct.pack(">H", l))
        else:
            hdr.append(127)
            hdr.extend(struct.pack(">Q", l))
        
        pkt = hdr + data_pkt
        for tid in targets:
            if tid in self.slaves:
                try:
                    self.slaves[tid]["conn"].sendall(pkt)
                except:
                    pass
    
    # ==================== 工作流 ====================
    
    def step_1_select_slaves(self):
        """選擇設備"""
        self.panel.stop()  # 暫停面板
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        print("\n[Step 1] 掃描網絡中...")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        p_data = SchemaCodec.encode(
            self.store.get(0x1001),
            {"server_ip": self.local_ip, "ws_url": f"ws://{self.local_ip}:8000"}
        )
        s.sendto(Proto.pack(0x1001, p_data), ('255.255.255.255', 9000))
        s.close()
        
        time.sleep(1.0)
        ids = list(self.slaves.keys())
        
        if not ids:
            print("❌ 未發現設備")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        print("\n--- 在線列表 ---")
        for i, sid in enumerate(ids):
            pid = self.config["mapping"].get(sid, {}).get("play_id", "?")
            print(f"{i+1}. {sid} (PlayID: {pid})")
        
        choice = input("\n👉 目標 (a/數字): ").lower()
        self.selected_targets = ids if choice == 'a' else [ids[int(x)-1] for x in choice.split(',')]
        print(f"✅ 已選中 {len(self.selected_targets)} 個設備")
        
        input("\n按 Enter 繼續...")
        self.panel.start()
    
    def step_2_prepare_data(self):
        """準備數據"""
        self.panel.stop()
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        if not self.selected_targets:
            print("⚠️ 請先執行 Step 1 選擇設備")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        pxld_files = [f for f in os.listdir('.') if f.endswith('.pxld')]
        if not pxld_files:
            print("❌ 目錄下找不到任何 .pxld 檔案")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        print("\n📂 [Step 2] 選擇動畫數據源:")
        for i, f in enumerate(pxld_files):
            print(f"  {i+1}. {f}")
        
        try:
            choice = int(input("👉 請選擇編號: ")) - 1
            if choice < 0 or choice >= len(pxld_files):
                raise ValueError
            path = pxld_files[choice]
        except:
            print("❌ 選擇無效")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        print(f"⚙️ 正在切分動畫: {path}...")
        self.prepared_data.clear()
        
        with PXLDv3Decoder(path) as decoder:
            needed_pids = {self.config["mapping"][tid].get("play_id") for tid in self.selected_targets}
            for pid in needed_pids:
                if pid is None:
                    continue
                print(f"  📦 提取 PlayID: {pid}...", end="", flush=True)
                data = bytearray()
                for frame in decoder.iterate_frames():
                    data.extend(decoder.get_slave_data(frame, pid))
                self.prepared_data[pid] = data
                print(f" OK ({len(data)//1024} KB)")
        
        print("✅ 動畫分片完成")
        input("\n按 Enter 繼續...")
        self.panel.start()
    
    def step_3_deploy(self):
        """
        部署階段：包含 SHA256 預檢與手動設備過濾
        """
        if not self.prepared_data:
            print("⚠️ 無預備數據，請先執行 Step 2")
            return

        # --- Phase 1: 預檢與顯示 Hex 狀態 ---
        self.panel.stop() # 暫時停止面板以進行交互
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        print("\n🔍 [Step 3.1] 正在讀取設備與本地數據狀態...")
        
        deploy_queue = [] # 儲存最終決定要上傳的目標 [ (tid, local_hex, remote_hex) ]
        
        # 遍歷已選的目標進行校驗查詢
        for i, tid in enumerate(self.selected_targets):
            node = self.slaves.get(tid)
            pid = self.config["mapping"][tid].get("play_id")
            data = self.prepared_data.get(pid)
            
            if not node or data is None:
                print(f"  [{i+1}] {tid:15} | ❌ 離線或無數據")
                continue
            
            # 計算本地數據的 SHA256 (Hex 格式)
            local_sha_bytes = hashlib.sha256(data).digest()
            local_sha_hex = local_sha_bytes.hex()[:16] # 顯示前16碼即可
            
            # 向 Slave 查詢遠端 SHA256
            node["query_event"].clear()
            self.send_pkt([tid], 0x2005, {"path": "/data.bin"})
            
            remote_sha_hex = "TIMEOUT"
            if node["query_event"].wait(timeout=120): # 等待 2 秒回報
                remote_sha_bytes = node.get("remote_sha")
                if remote_sha_bytes:
                    remote_sha_hex = remote_sha_bytes.hex()[:16]
                else:
                    remote_sha_hex = "NONE(Empty)"
            
            status_mark = "✔ MATCH" if local_sha_hex == remote_sha_hex else "✖ DIFF"
            print(f"  [{i+1}] {tid:12} | Local:{local_sha_hex} | Remote:{remote_sha_hex} | [{status_mark}]")
            
            deploy_queue.append((tid, local_sha_hex, remote_sha_hex))

        if not deploy_queue:
            input("\n❌ 沒有可部署的設備，按 Enter 返回...")
            self.panel.start()
            return

        # --- Phase 2: 手動選擇上傳目標 ---
        print("\n" + "-"*60)
        choice = input("👉 輸入編號開始上傳 (例如: 1,3,5), 輸入 'a' 僅上傳不一致者, 輸入 'do_all' 全選: ").lower()
        
        final_targets = []
        if choice == 'do_all':
            final_targets = [item[0] for item in deploy_queue]
        elif choice == 'a':
            final_targets = [item[0] for item in deploy_queue if item[1] != item[2]]
        else:
            try:
                idxs = [int(x.strip()) - 1 for x in choice.split(',')]
                final_targets = [deploy_queue[i][0] for i in idxs if 0 <= i < len(deploy_queue)]
            except:
                print("❌ 輸入錯誤，操作已取消")
                self.panel.start()
                return

        if not final_targets:
            print("ℹ️ 無設備被選中上傳")
            time.sleep(1)
            self.panel.start()
            return

        # --- Phase 3: 正式並行部署 (帶監控面板) ---
        self.panel.start()
        
        # 標記非上傳目標的狀態為待機
        for tid in self.selected_targets:
            if tid not in final_targets:
                self.panel.update_device(tid, status="待機", upload_progress=100)
            else:
                self.panel.update_device(tid, status="傳輸中", upload_progress=0, upload_speed=0)

        # 限制並行數量，保護 MCU 接收緩衝區不被網路風暴淹沒
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self._deploy_to_single_slave, tid): tid for tid in final_targets}
            
            for future in futures:
                tid = futures[future]
                try:
                    future.result()
                    # 傳輸成功後更新為待機狀態
                    self.panel.update_device(tid, status="待機", upload_progress=100)
                except Exception as e:
                    self.panel.update_device(tid, status="錯誤", error_msg=str(e))
        
        time.sleep(2)
        print("\n✅ 選定設備部署操作完成")


    def _deploy_to_single_slave(self, tid):
        """單設備部署邏輯"""
        node = self.slaves.get(tid)
        pid = self.config["mapping"][tid].get("play_id")
        data = self.prepared_data.get(pid)
        
        if not node or data is None:
            raise Exception(f"無數據或設備離線")
        
        local_sha = hashlib.sha256(data).digest()
        target_path = "/data.bin"
        total_len = len(data)
        
        # 初始化統計
        self.deploy_stats[tid] = {"start_time": time.time(), "bytes_sent": 0}
        
        # Phase 1: SHA256 校驗
        self.panel.update_device(tid, uploaded_bytes=0, total_bytes=total_len)
        
        node["query_event"].clear()
        self.send_pkt([tid], 0x2005, {"path": target_path})
        
        if node["query_event"].wait(timeout=10.0):
            if node.get("remote_sha") == local_sha:
                self.panel.update_device(tid, status="待機", upload_progress=100)
                return
        
        # Phase 2: FILE_BEGIN
        self.send_pkt([tid], 0x2001, {
            "file_id": 1,
            "total_size": total_len,
            "chunk_size": 1024,
            "sha256": local_sha,
            "path": target_path
        })
        time.sleep(0.1)
        
        # Phase 3: FILE_CHUNK (實時更新面板)
        chunk_size = 1024
        
        for off in range(0, total_len, chunk_size):
            chunk = data[off : off + chunk_size]
            
            node["ack_event"].clear()
            self.send_pkt([tid], 0x2002, {
                "file_id": 1,
                "offset": off,
                "data": chunk
            })
            
            if not node["ack_event"].wait(timeout=120):
                raise Exception(f"Offset {off} 超時")
            
            # 更新統計
            done = off + len(chunk)
            self.deploy_stats[tid]["bytes_sent"] = done
            elapsed = time.time() - self.deploy_stats[tid]["start_time"]
            speed = (done / 1024) / elapsed if elapsed > 0 else 0
            progress = (done / total_len) * 100
            
            # 更新面板
            self.panel.update_device(
                tid,
                upload_progress=progress,
                upload_speed=speed,
                uploaded_bytes=done,
                total_bytes=total_len
            )
        
        # Phase 4: FILE_END
        self.send_pkt([tid], 0x2003, {"file_id": 1})
        self.config["mapping"][tid]["last_sha"] = local_sha.hex()
        self.save_config()
    
    def step_4_sync_play(self):
        """同步播放"""
        self.panel.stop()
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        if not self.selected_targets:
            print("⚠️ 未選擇設備,請先執行 Step 1")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        # 選擇 MP3
        mp3_files = [f for f in os.listdir('.') if f.endswith('.mp3')]
        if not mp3_files:
            print("❌ 當前目錄下找不到 MP3 文件")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        print(f"\n🎵 [音訊準備] 模式: {AUDIO_MODE}")
        for i, f in enumerate(mp3_files):
            print(f"  {i+1}. {f} ({os.path.getsize(f)//1024} KB)")
        
        try:
            choice_idx = int(input("👉 請選擇 MP3 編號 (輸入 0 取消): ")) - 1
            if choice_idx < 0:
                self.panel.start()
                return
            selected_mp3 = mp3_files[choice_idx]
        except (ValueError, IndexError):
            print("❌ 選擇無效")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        # 預備 Slave
        print(f"⚙️ 正在通知 Slave 預備數據...")
        for tid in self.selected_targets:
            self.panel.update_device(tid, status="待機", current_frame=0, total_frames=0)
        
        self.send_pkt(self.selected_targets, 0x3009, {
            "file_name": "data.bin",
            "block_id": 0,
            "play_mode": 1
        })
        time.sleep(0.5)
        
        # 擊發確認
        print("\n" + "!"*40)
        print("     所有系統就緒,等待擊發指令")
        print(f"     當前延遲設定: {self.config.get('sync_delay_ms', 0)} ms")
        print("     輸入 'go' 開始播放 | 輸入 'q' 取消預備")
        print("!"*40)
        trigger = input("🚀 指令: ").lower()
        
        if trigger != 'go':
            print("🛑 播放已取消")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        # 標記播放狀態
        for tid in self.selected_targets:
            self.panel.update_device(tid, status="播放中", render_fps=0, current_frame=0)
        
        # 啟動監控面板
        self.panel.start()
        
        # 同步播放
        delay_ms = self.config.get("sync_delay_ms", 150)
        delay_sec = abs(delay_ms) / 1000.0
        
        if delay_ms >= 0:
            self._start_audio_stream(selected_mp3)
            if delay_ms > 0:
                time.sleep(delay_sec)
            self.send_pkt(self.selected_targets, 0x300A, {})
        else:
            self.send_pkt(self.selected_targets, 0x300A, {})
            time.sleep(delay_sec)
            self._start_audio_stream(selected_mp3)
        
        # 等待播放結束
        while self.is_playing:
            time.sleep(0.5)
        
        # 播放完畢,恢復待機
        for tid in self.selected_targets:
            self.panel.update_device(tid, status="待機")
    
    def _start_audio_stream(self, file_path):
        """啟動音訊流"""
        self.is_playing = True
        
        def _play_task():
            try:
                if AUDIO_MODE == 'miniaudio':
                    with miniaudio.PlaybackDevice() as device:
                        stream = miniaudio.stream_file(file_path)
                        device.start(stream)
                        while device.is_active and self.running and self.is_playing:
                            time.sleep(0.1)
                        device.stop()
                else:
                    if not mixer.get_init():
                        mixer.init()
                    mixer.music.load(file_path)
                    mixer.music.play()
                    while mixer.music.get_busy() and self.running and self.is_playing:
                        time.sleep(0.1)
                    mixer.music.stop()
            except Exception as e:
                print(f"\n[Audio Error] {e}")
            finally:
                self.is_playing = False
        
        threading.Thread(target=_play_task, daemon=True).start()
    
    def stop_all(self):
        """全局停止"""
        self.is_playing = False
        
        if self.selected_targets:
            self.send_pkt(self.selected_targets, 0x3002, {})
            for tid in self.selected_targets:
                self.panel.update_device(tid, status="待機")
        
        if AUDIO_MODE == 'pygame':
            try:
                if mixer.get_init():
                    mixer.music.stop()
            except:
                pass
    
    def main_loop(self):
        """主循環"""
        while self.running:
            # 暫停面板,顯示菜單
            self.panel.stop()
            ConsoleUI.clear_screen()
            ConsoleUI.show_cursor()
            
            print("\n" + "="*50)
            print(" 🎬 NetBus Master Control Panel")
            print("="*50)
            print(" 1. Select Devices     | 掃描並選擇設備")
            print(" 2. Slice Animation    | 切分動畫數據")
            print(" 3. Deploy             | 部署到設備 (帶實時監控)")
            print(" 4. Sync Play          | 同步播放 (帶性能監控)")
            print(" s. STOP ALL           | 緊急停止")
            print(" q. Exit               | 退出程序")
            print("="*50)
            
            ch = input("\n👉 請選擇操作: ").lower()
            
            if ch == '1':
                self.step_1_select_slaves()
            elif ch == '2':
                self.step_2_prepare_data()
            elif ch == '3':
                self.step_3_deploy()
            elif ch == '4':
                self.step_4_sync_play()
            elif ch == 's':
                self.stop_all()
                print("✅ 已發送停止信號")
                input("\n按 Enter 繼續...")
            elif ch == 'q':
                self.stop_all()
                self.running = False
                break
        
        # 清理
        self.panel.stop()
        ConsoleUI.show_cursor()


if __name__ == "__main__":
    app = NetBusMaster()
    try:
        app.main_loop()
    except KeyboardInterrupt:
        print("\n\n🛑 用戶中斷")
    finally:
        app.panel.stop()
        ConsoleUI.show_cursor()
        print("\n再見! 👋")

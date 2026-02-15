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
from collections import defaultdict, deque

# ==================== 音頻模式自動檢測 (修復導入) ====================
AUDIO_MODE = 'miniaudio'
mixer = None  # 全局變量

try:
    import miniaudio
except ImportError:
    AUDIO_MODE = 'pygame'
    try:
        import pygame
        pygame.mixer.init()
        mixer = pygame.mixer  # 正確引用
    except ImportError:
        print("⚠️ 警告: pygame 和 miniaudio 都未安裝,音訊功能不可用")
        AUDIO_MODE = None

print(f"[Audio Mode] {AUDIO_MODE}")

# ==================== 路徑初始化 ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(SCRIPT_DIR)

# ==================== 協議層導入 ====================
try:
    from slave.lib.proto import Proto, StreamParser
    from slave.lib.schema_loader import SchemaStore
    from slave.lib.schema_codec import SchemaCodec
    from tools.PXLDv3Splitter import PXLDv3Decoder
except ImportError as e:
    print(f"❌ 導入錯誤: {e}")
    sys.exit(1)


# ==================== 增強版設備監控模型 ====================
class DeviceMonitor:
    """
    多階段數據融合監控模型
    """
    
    def __init__(self, device_id):
        # ========== 基礎信息 ==========
        self.device_id = device_id
        self.play_id = None
        self.status = "離線"
        
        # ========== 傳輸階段數據 ==========
        self.upload_progress = 0.0
        self.upload_speed = 0.0
        self.uploaded_bytes = 0
        self.total_bytes = 0
        self.upload_start_time = 0
        
        # ========== 播放階段數據 ==========
        self.total_frames = 0
        self.current_frame = 0
        self.render_fps = 0.0
        self.calculated_fps = 0.0
        
        # ========== 性能監控 ==========
        self.mem_free = 0
        self.block_count = 0
        self.avg_fps = 0.0
        
        # ========== 歷史數據 (用於計算) ==========
        self.frame_history = deque(maxlen=10)
        self.last_update = time.time()
        self.last_frame_update = time.time()
        
        # ========== 錯誤信息 ==========
        self.error_msg = ""
        
        # ========== 線程安全鎖 ==========
        self.lock = threading.Lock()
    
    def update_frame(self, frame_num):
        """更新当前帧号并计算实时 FPS"""
        with self.lock:
            now = time.time()
            
            # 🔧 如果是第一次更新，只记录不计算
            if self.current_frame == 0 or self.last_frame_update == 0:
                self.current_frame = frame_num
                self.last_frame_update = now
                return
            
            # 🔧 计算帧差和时间差
            frame_delta = frame_num - self.current_frame
            time_delta = now - self.last_frame_update
            
            # 🔧 简单直接：本次帧号 - 上次帧号 / 时间差
            if time_delta > 0 and frame_delta > 0:
                self.calculated_fps = frame_delta / time_delta
            
            # 更新记录
            self.current_frame = frame_num
            self.last_frame_update = now
    
    def get_play_progress(self):
        """返回播放進度百分比"""
        with self.lock:
            if self.total_frames > 0:
                return (self.current_frame / self.total_frames) * 100
            return 0.0
    
    def reset_play_stats(self):
        """重置播放統計數據"""
        with self.lock:
            self.current_frame = 0
            self.render_fps = 0.0
            self.calculated_fps = 0.0
            self.block_count = 0
            self.avg_fps = 0.0
            self.frame_history.clear()


# ==================== 終端 UI 渲染引擎 ====================
class ConsoleUI:
    """ANSI 轉義序列終端控制"""
    
    @staticmethod
    def clear_screen():
        print("\033[2J\033[H", end="")
    
    @staticmethod
    def move_cursor(row, col):
        print(f"\033[{row};{col}H", end="")
    
    @staticmethod
    def hide_cursor():
        print("\033[?25l", end="")
    
    @staticmethod
    def show_cursor():
        print("\033[?25h", end="")
    
    @staticmethod
    def get_color(value, threshold_good=80, threshold_warn=50):
        if value >= threshold_good:
            return "\033[92m"
        elif value >= threshold_warn:
            return "\033[93m"
        else:
            return "\033[91m"
    
    @staticmethod
    def reset_color():
        return "\033[0m"
    
    @staticmethod
    def draw_progress_bar(percent, width=30):
        filled = int(width * percent / 100)
        bar = "█" * filled + "░" * (width - filled)
        color = ConsoleUI.get_color(percent)
        return f"{color}{bar}{ConsoleUI.reset_color()} {percent:5.1f}%"


# ==================== 監控面板核心 ====================
class MonitorPanel:
    """實時監控面板"""
    
    def __init__(self):
        self.monitors = {}
        self.lock = threading.Lock()
        self.running = False
        self.refresh_rate = 0.1
        self.render_thread = None
        self.interactive_mode = False
    
    def register_device(self, device_id, play_id=None, total_frames=0):
        with self.lock:
            if device_id not in self.monitors:
                monitor = DeviceMonitor(device_id)
                monitor.play_id = play_id
                monitor.total_frames = total_frames
                monitor.status = "待機"
                self.monitors[device_id] = monitor
            else:
                monitor = self.monitors[device_id]
                if play_id is not None:
                    monitor.play_id = play_id
                if total_frames > 0:
                    monitor.total_frames = total_frames
    
    def update_device(self, device_id, **kwargs):
        with self.lock:
            if device_id in self.monitors:
                monitor = self.monitors[device_id]
                
                if 'current_frame' in kwargs:
                    monitor.update_frame(kwargs.pop('current_frame'))
                
                for key, value in kwargs.items():
                    if hasattr(monitor, key):
                        setattr(monitor, key, value)
                
                monitor.last_update = time.time()
    
    def remove_device(self, device_id):
        with self.lock:
            if device_id in self.monitors:
                self.monitors[device_id].status = "離線"
    
    def start(self, interactive=False):
        if not self.running:
            self.running = True
            self.interactive_mode = interactive
            ConsoleUI.hide_cursor()
            ConsoleUI.clear_screen()
            self.render_thread = threading.Thread(target=self._render_loop, daemon=True)
            self.render_thread.start()
    
    def stop(self):
        self.running = False
        if self.render_thread:
            self.render_thread.join(timeout=1.0)
        ConsoleUI.show_cursor()
    
    def _render_loop(self):
        while self.running:
            self._render_frame()
            time.sleep(self.refresh_rate)
    
    def _render_frame(self):
        with self.lock:
            ConsoleUI.move_cursor(1, 1)
            
            title = "╔════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗"
            subtitle = f"║  🎬 NetBus Master Monitor  │  Devices: {len(self.monitors)}  │  Time: {datetime.now().strftime('%H:%M:%S')}                                 ║"
            divider = "╠════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣"
            
            print(title)
            print(subtitle)
            print(divider)
            
            if not self.monitors:
                print("║  [無設備在線]                                                                                                      ║")
            else:
                for device_id, monitor in sorted(self.monitors.items()):
                    self._render_device_row(monitor)
            
            bottom = "╠════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╣"
            print(bottom)
            
            if self.interactive_mode:
                controls = "║  [SPACE] 暫停/繼續  │  [S] 停止播放  │  [Q] 退出                                                              ║"
                print(controls)
            
            footer = "╚════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝"
            print(footer)
            print()
    
    def _render_device_row(self, monitor: DeviceMonitor):
        device_str = f"{monitor.device_id[:12]:<12}"
        play_id_str = f"P{monitor.play_id:02d}" if monitor.play_id is not None else "---"
        
        status_colors = {
            "離線": "\033[90m",
            "待機": "\033[96m",
            "傳輸中": "\033[93m",
            "播放中": "\033[92m",
            "暫停": "\033[95m",
            "錯誤": "\033[91m"
        }
        status_color = status_colors.get(monitor.status, "\033[0m")
        status_str = f"{status_color}{monitor.status:<6}{ConsoleUI.reset_color()}"
        
        if monitor.status == "傳輸中":
            progress_bar = ConsoleUI.draw_progress_bar(monitor.upload_progress, width=20)
            speed_str = f"{monitor.upload_speed:>6.1f} KB/s"
            size_str = f"{monitor.uploaded_bytes//1024}/{monitor.total_bytes//1024} KB"
            info = f"{progress_bar} │ {speed_str} │ {size_str}"
        
        elif monitor.status in ["播放中", "暂停"]:
            play_progress = monitor.get_play_progress()
            
            # 🔧 修复: 显示真实计算的 FPS
            calc_fps_color = ConsoleUI.get_color(monitor.calculated_fps, threshold_good=25, threshold_warn=15)
            calc_fps_str = f"{calc_fps_color}{monitor.calculated_fps:>5.1f}{ConsoleUI.reset_color()}"
            
            # 当前帧/总帧
            frame_str = f"{monitor.current_frame}/{monitor.total_frames}"
            progress_percent = f"{play_progress:>5.1f}%"
            
            # 内存显示
            mem_mb = monitor.mem_free / (1024 * 1024)
            mem_color = ConsoleUI.get_color(mem_mb, threshold_good=10, threshold_warn=5)
            mem_str = f"{mem_color}{mem_mb:>6.1f} MB{ConsoleUI.reset_color()}"
            
            # 🔧 简化显示: 只显示 Real_FPS (真实渲染帧率)
            info = f"Progress: {progress_percent} │ Frame: {frame_str:<12} │ FPS: {calc_fps_str} │ Mem: {mem_str}"
        
        elif monitor.status == "錯誤":
            info = f"\033[91m{monitor.error_msg[:70]}\033[0m"
        
        else:
            idle_time = int(time.time() - monitor.last_update)
            info = f"閒置 {idle_time}s"
        
        line = f"║ {device_str} │ {play_id_str} │ {status_str} │ {info:<80} ║"
        print(line)


# ==================== NetBusMaster 主類 ====================
class NetBusMaster:
    def __init__(self, config_file="slave_map.json"):
        self.store = SchemaStore(dir_path=f"{PROJECT_ROOT}/slave/schema")
        self.slaves = {}
        self.running = True
        self.local_ip = self.get_local_ip()
        
        self.is_playing = False
        self.is_paused = False
        self.play_lock = threading.Lock()
        
        self.panel = MonitorPanel()
        
        self.config_file = config_file
        self.config = self.load_config()
        self.selected_targets = []
        self.prepared_data = {}
        self.pxld_metadata = {}
        
        threading.Thread(target=self.start_ws_server, daemon=True).start()
    
    def load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"sync_delay_ms": 150, "mapping": {}}
    
    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)
    
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
        print(f"[WS Server] 監聽 0.0.0.0:8000")
        
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except:
                break
    
    def handle_client(self, conn, addr):
        cid = f"PENDING_{addr[1]}"
        
        try:
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
            
            resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n")
            conn.send(resp.encode())
            
            if cid not in self.config["mapping"]:
                pids = [v["play_id"] for v in self.config["mapping"].values() if "play_id" in v]
                new_pid = max(pids) + 1 if pids else 0
                self.config["mapping"][cid] = {"play_id": new_pid, "last_sha": ""}
                self.save_config()
            
            play_id = self.config["mapping"][cid]["play_id"]
            total_frames = self.pxld_metadata.get(play_id, {}).get("total_frames", 0)
            
            self.panel.register_device(cid, play_id, total_frames)
            
            self.slaves[cid] = {
                "conn": conn,
                "addr": addr,
                "parser": StreamParser(),
                "ack_event": threading.Event(),
                "query_event": threading.Event(),
                "remote_sha": None
            }
            
            parser = self.slaves[cid]["parser"]
            while self.running:
                raw = conn.recv(4096)
                if not raw:
                    break
                
                if raw[0] == 0x82:
                    plen = raw[1] & 0x7F
                    off = 2
                    if plen == 126:
                        off = 4
                    elif plen == 127:
                        off = 10
                    parser.feed(raw[off:])
                else:
                    parser.feed(raw)
                
                for ver, addr_pkt, cmd, payload in parser.pop():
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
        
        # ========== 0x1102: 状态心跳 ==========
        if cmd == 0x1102:
            try:
                status_data = json.loads(args["status_json"])
                
                # 🔧 修复: MCU 回报的 render_fps 实际是当前帧号
                current_frame = status_data.get('render_fps', 0)  # ✅ 这是帧号
                mem_free = status_data.get('mem_free', 0)
                real_id = status_data.get('id')
                
                # 🔧 更新当前帧号 (触发 FPS 计算)
                self.panel.update_device(
                    cid,
                    current_frame=current_frame,  # ✅ 更新帧号
                    mem_free=mem_free
                )
                
                # 设备 ID 转移
                if real_id and real_id != cid:
                    if cid in self.panel.monitors:
                        self.panel.monitors[real_id] = self.panel.monitors.pop(cid)
                        self.panel.monitors[real_id].device_id = real_id
                    self.slaves[real_id] = self.slaves.pop(cid)
                    cid = real_id
            
            except Exception as e:
                pass
        
        elif cmd == 0x3012:
            block_id = args.get("block_id", 0)
            current_frame = args.get("end_frame", 0)
            actual_fps = args.get("actual_fps", 0) / 100.0
            
            self.panel.update_device(
                cid,
                current_frame=current_frame
            )
            
            if cid in self.panel.monitors:
                monitor = self.panel.monitors[cid]
                with monitor.lock:
                    monitor.block_count += 1
                    monitor.avg_fps = (monitor.avg_fps * (monitor.block_count - 1) + actual_fps) / monitor.block_count
        
        elif cmd == 0x2004:
            if cid in self.slaves:
                self.slaves[cid]["ack_event"].set()
        
        elif cmd == 0x2006:
            if cid in self.slaves:
                self.slaves[cid]["remote_sha"] = args["sha256"]
                self.slaves[cid]["query_event"].set()
        
        return cid
    
    def send_pkt(self, targets, cmd_id, args):
        c_def = self.store.get(cmd_id)
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
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
        
        pkt = hdr + data_pkt
        
        for tid in targets:
            if tid in self.slaves:
                try:
                    self.slaves[tid]["conn"].sendall(pkt)
                except:
                    pass
    
    # ==================== Step 1: 選擇設備 ====================
    def step_1_select_slaves(self):
        self.panel.stop()
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        print("\n[Step 1] 正在廣播發現包...")
        
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        p_data = SchemaCodec.encode(
            self.store.get(0x1001),
            {"server_ip": self.local_ip, "ws_url": f"ws://{self.local_ip}:8000"}
        )
        s.sendto(Proto.pack(0x1001, p_data), ('255.255.255.255', 9000))
        s.close()
        
        time.sleep(3)
        
        # --- 修改排序邏輯 ---
        # 取得所有在線設備 ID
        online_ids = list(self.slaves.keys())
        
        if not online_ids:
            print("❌ 未發現任何在線設備")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return

        # 根據 PlayID 進行排序 (如果沒定義 PlayID 則排最後，預設給個很大的數字 999)
        sorted_ids = sorted(
            online_ids, 
            key=lambda sid: self.config["mapping"].get(sid, {}).get("play_id", 999)
        )
        # ------------------

        print(f"\n✅ 發現 {len(sorted_ids)} 個設備 (按 PlayID 排序):")
        print("-" * 50)
        for i, sid in enumerate(sorted_ids):
            pid = self.config["mapping"].get(sid, {}).get("play_id", "N/A")
            print(f"  {i+1:2d}. {sid:15} (PlayID: {pid})")
        
        choice = input("\n👉 選擇目標 (a=全選 / 逗號分隔編號): ").lower()
        
        if choice == 'a':
            self.selected_targets = sorted_ids  # 使用排序後的列表
        else:
            try:
                # 根據用戶輸入的編號從排序後的 sorted_ids 中提取
                indices = [int(x.strip()) - 1 for x in choice.split(',')]
                self.selected_targets = [sorted_ids[i] for i in indices if 0 <= i < len(sorted_ids)]
            except:
                print("❌ 輸入無效")
                input("\n按 Enter 繼續...")
                self.panel.start()
                return
        
        print(f"\n✅ 已選中 {len(self.selected_targets)} 個設備")
        input("\n按 Enter 繼續...")
        self.panel.start()
    
    # ==================== Step 2: 準備數據 (修復版) ====================
    def _save_bins(self):
        """將 prepared_data 保存到 bins/ 目錄"""
        bins_dir = os.path.join('.', 'bins')
        os.makedirs(bins_dir, exist_ok=True)

        for pid, data in self.prepared_data.items():
            bin_path = os.path.join(bins_dir, f'pid_{pid}.bin')
            with open(bin_path, 'wb') as f:
                f.write(data)
            print(f"  💾 已保存 {bin_path} ({len(data)//1024} KB)")

    def _load_bins(self):
        """從 bins/ 目錄載入 bin 檔案到 prepared_data"""
        bins_dir = os.path.join('.', 'bins')
        needed_pids = {self.config["mapping"][tid].get("play_id") for tid in self.selected_targets}
        needed_pids.discard(None)

        self.prepared_data.clear()
        self.pxld_metadata.clear()

        loaded = 0
        missing = []
        for pid in needed_pids:
            bin_path = os.path.join(bins_dir, f'pid_{pid}.bin')
            if os.path.isfile(bin_path):
                with open(bin_path, 'rb') as f:
                    self.prepared_data[pid] = bytearray(f.read())
                print(f"  📂 已載入 pid_{pid}.bin ({len(self.prepared_data[pid])//1024} KB)")
                loaded += 1
            else:
                missing.append(pid)

        if missing:
            print(f"  ⚠️ 缺少 PlayID: {missing}")

        return loaded, missing

    def step_2_prepare_data(self):
        """切分 PXLD 動畫數據"""
        self.panel.stop()
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()

        if not self.selected_targets:
            print("⚠️ 請先執行 Step 1 選擇設備")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return

        # 檢查 bins/ 是否有現成的 bin 檔案
        bins_dir = os.path.join('.', 'bins')
        has_bins = os.path.isdir(bins_dir) and any(f.endswith('.bin') for f in os.listdir(bins_dir))

        pxld_files = [f for f in os.listdir('.') if f.endswith('.pxld')]

        if has_bins:
            bin_files = sorted(f for f in os.listdir(bins_dir) if f.endswith('.bin'))
            print("\n📂 [Step 2] 選擇數據來源:")
            print(f"  1. 從 bins/ 載入已切分的數據 ({len(bin_files)} 個檔案)")
            if pxld_files:
                print(f"  2. 重新從 .pxld 切分")

            try:
                src = input("\n👉 請選擇 (1/2): ").strip()
            except:
                src = "1"

            if src == "1":
                print(f"\n⚙️ 正在從 bins/ 載入...")
                loaded, missing = self._load_bins()
                if loaded > 0:
                    print(f"\n✅ 已載入 {loaded} 個 PlayID 的數據")
                else:
                    print("❌ 沒有載入任何數據")
                input("\n按 Enter 繼續...")
                self.panel.start()
                return

        if not pxld_files:
            print("❌ 當前目錄下找不到 .pxld 文件")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return

        print("\n📂 [Step 2] 選擇動畫源:")
        for i, f in enumerate(pxld_files):
            size_kb = os.path.getsize(f) // 1024
            print(f"  {i+1}. {f} ({size_kb} KB)")

        try:
            choice = int(input("\n👉 請選擇編號: ")) - 1
            if choice < 0 or choice >= len(pxld_files):
                raise ValueError
            path = pxld_files[choice]
        except:
            print("❌ 選擇無效")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        print(f"\n⚙️ 正在解析動畫: {path}...")
        
        self.prepared_data.clear()
        self.pxld_metadata.clear()
        
        try:
            with PXLDv3Decoder(path) as decoder:
                # 🔧 修復: 從打印信息獲取總幀數
                # 根據您的輸出: "總影格: 10707"
                # PXLDv3Decoder 可能沒有 header 屬性,而是直接在 __enter__ 時打印
                
                # 嘗試多種方法獲取總幀數
                total_frames = 0
                if hasattr(decoder, 'total_frames'):
                    total_frames = decoder.total_frames
                elif hasattr(decoder, 'frame_count'):
                    total_frames = decoder.frame_count
                else:
                    # 如果都沒有,則通過遍歷計算
                    print("  ⚙️ 正在計算總幀數...")
                    total_frames = sum(1 for _ in decoder.iterate_frames())
                    # 重新打開文件以便後續切分
                    decoder.__exit__(None, None, None)
                    decoder = PXLDv3Decoder(path).__enter__()
                
                print(f"  📊 總幀數: {total_frames}")
                
                # 提取所需 PlayID 數據
                needed_pids = {self.config["mapping"][tid].get("play_id") for tid in self.selected_targets}
                
                for pid in needed_pids:
                    if pid is None:
                        continue
                    
                    print(f"  📦 提取 PlayID {pid}...", end="", flush=True)
                    
                    data = bytearray()
                    frame_count = 0
                    
                    for frame in decoder.iterate_frames():
                        slave_data = decoder.get_slave_data(frame, pid)
                        if slave_data:
                            data.extend(slave_data)
                        frame_count += 1
                    
                    self.prepared_data[pid] = data
                    self.pxld_metadata[pid] = {"total_frames": total_frames}
                    
                    # 更新監控面板的 total_frames
                    for tid in self.selected_targets:
                        if self.config["mapping"][tid].get("play_id") == pid:
                            self.panel.register_device(tid, pid, total_frames)
                    
                    print(f" OK ({len(data)//1024} KB, {total_frames} Frames)")
        
        except Exception as e:
            print(f"\n❌ 解析失敗: {e}")
            import traceback
            traceback.print_exc()
            input("\n按 Enter 繼續...")
            self.panel.start()
            return

        # 保存 bin 檔案到 bins/
        print("\n💾 正在保存切分數據到 bins/...")
        self._save_bins()

        print("\n✅ 動畫數據準備完成")
        input("\n按 Enter 繼續...")
        self.panel.start()
    
    # ==================== Step 3: 部署數據 ====================
    def step_3_deploy(self):
        if not self.prepared_data:
            print("⚠️ 無預備數據,請先執行 Step 2")
            time.sleep(1)
            return
        
        self.panel.stop()
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        print(f"\n🔍 [Step 3.1] 正在檢查 {len(self.selected_targets)} 個設備狀態...")
        
        local_sha_cache = {}
        for tid in self.selected_targets:
            pid = self.config["mapping"][tid].get("play_id")
            data = self.prepared_data.get(pid)
            if data:
                sha = hashlib.sha256(data).digest().hex()[:16]
                local_sha_cache[tid] = sha
            else:
                local_sha_cache[tid] = None
        
        valid_tids = []
        for tid in self.selected_targets:
            node = self.slaves.get(tid)
            if node and local_sha_cache[tid]:
                node["query_event"].clear()
                node["remote_sha"] = None
                valid_tids.append(tid)
                self.send_pkt([tid], 0x2005, {"path": "/data.bin"})
        tout = 120
        print(f"⏳ 等待設備回報 (Timeout: {tout}s)...")
        start_wait = time.time()
        while time.time() - start_wait < tout:
            if all(self.slaves[tid]["query_event"].is_set() for tid in valid_tids):
                break
            time.sleep(0.1)
        
        deploy_queue = []
        print(f"\n{'編號':<5} | {'設備ID':<15} | {'本地SHA':<16} | {'遠程SHA':<16} | {'狀態'}")
        print("-" * 75)
        
        for i, tid in enumerate(self.selected_targets):
            local_sha = local_sha_cache.get(tid)
            node = self.slaves.get(tid)
            
            if not node or not local_sha:
                print(f"[{i+1:02}]  {tid:15} | {'離線或無數據':^50}")
                continue
            
            remote_sha_bytes = node.get("remote_sha")
            remote_sha = remote_sha_bytes.hex()[:16] if remote_sha_bytes else "TIMEOUT"
            
            is_match = (local_sha == remote_sha)
            status = "✔ 匹配" if is_match else "✖ 不同"
            
            print(f"[{i+1:02}]  {tid:15} | {local_sha} | {remote_sha:16} | {status}")
            deploy_queue.append((tid, local_sha, remote_sha))
        
        if not deploy_queue:
            input("\n❌ 無可用設備,按 Enter 返回...")
            self.panel.start()
            return
        
        print("\n" + "-" * 75)
        choice = input("👉 輸入編號上傳 (例: 1,3,5) | 'a' 僅上傳不一致 | 'all' 全選: ").lower()
        
        final_targets = []
        if choice == 'all':
            final_targets = [item[0] for item in deploy_queue]
        elif choice == 'a':
            final_targets = [item[0] for item in deploy_queue if item[1] != item[2]]
        else:
            try:
                idxs = [int(x.strip()) - 1 for x in choice.split(',')]
                final_targets = [deploy_queue[i][0] for i in idxs if 0 <= i < len(deploy_queue)]
            except:
                print("❌ 輸入錯誤")
                self.panel.start()
                return
        
        if not final_targets:
            print("ℹ️ 無設備被選中")
            time.sleep(1)
            self.panel.start()
            return
        
        self.panel.start()
        
        for tid in self.selected_targets:
            if tid not in final_targets:
                self.panel.update_device(tid, status="待機", upload_progress=100)
            else:
                self.panel.update_device(tid, status="傳輸中", upload_progress=0)
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(self._deploy_to_single_slave, tid): tid for tid in final_targets}
            
            for future in futures:
                tid = futures[future]
                try:
                    future.result()
                    self.panel.update_device(tid, status="待機", upload_progress=100)
                except Exception as e:
                    self.panel.update_device(tid, status="錯誤", error_msg=str(e))
        
        time.sleep(2)
        print("\n✅ 部署完成")
    
    def _deploy_to_single_slave(self, tid):
        node = self.slaves.get(tid)
        pid = self.config["mapping"][tid].get("play_id")
        data = self.prepared_data.get(pid)
        
        if not node or data is None:
            raise Exception("無數據或離線")
        
        local_sha = hashlib.sha256(data).digest()
        target_path = "/data.bin"
        total_len = len(data)
        chunk_size = 1024
        
        start_time = time.time()
        
        self.panel.update_device(
            tid,
            uploaded_bytes=0,
            total_bytes=total_len,
            upload_start_time=start_time
        )
        
        self.send_pkt([tid], 0x2001, {
            "file_id": 1,
            "total_size": total_len,
            "chunk_size": chunk_size,
            "sha256": local_sha,
            "path": target_path
        })
        time.sleep(0.1)
        
        for off in range(0, total_len, chunk_size):
            chunk = data[off : off + chunk_size]
            
            node["ack_event"].clear()
            self.send_pkt([tid], 0x2002, {
                "file_id": 1,
                "offset": off,
                "data": chunk
            })
            
            if not node["ack_event"].wait(timeout=5.0):
                raise Exception(f"Offset {off} 超時")
            
            done = off + len(chunk)
            elapsed = time.time() - start_time
            speed = (done / 1024) / elapsed if elapsed > 0 else 0
            progress = (done / total_len) * 100
            
            self.panel.update_device(
                tid,
                upload_progress=progress,
                upload_speed=speed,
                uploaded_bytes=done
            )
        
        self.send_pkt([tid], 0x2003, {"file_id": 1})
        
        self.config["mapping"][tid]["last_sha"] = local_sha.hex()
        self.save_config()
    
    # ==================== Step 4: 同步播放 (修復音訊) ====================
    def step_4_sync_play(self):
        global mixer  # 使用全局 mixer 變量
        
        self.panel.stop()
        ConsoleUI.clear_screen()
        ConsoleUI.show_cursor()
        
        if not self.selected_targets:
            print("⚠️ 請先執行 Step 1")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        if AUDIO_MODE is None:
            print("❌ 音訊模塊未安裝,無法播放")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        mp3_files = [f for f in os.listdir('.') if f.endswith('.mp3')]
        if not mp3_files:
            print("❌ 找不到 MP3 文件")
            input("\n按 Enter 繼續...")
            self.panel.start()
            return
        
        print(f"\n🎵 [音訊準備] 模式: {AUDIO_MODE}")
        for i, f in enumerate(mp3_files):
            print(f"  {i+1}. {f}")
        
        try:
            choice = int(input("\n👉 選擇編號 (0=取消): ")) - 1
            if choice < 0:
                self.panel.start()
                return
            selected_mp3 = mp3_files[choice]
        except:
            print("❌ 選擇無效")
            self.panel.start()
            return
        
        print(f"\n⚙️ 正在預備設備...")
        
        for tid in self.selected_targets:
            self.panel.update_device(tid, status="待機")
            if tid in self.panel.monitors:
                self.panel.monitors[tid].reset_play_stats()
        
        self.send_pkt(self.selected_targets, 0x3009, {
            "file_name": "data.bin",
            "block_id": 0,
            "play_mode": 0
        })
        time.sleep(0.5)
        
        print("\n" + "!" * 50)
        print("     系統就緒,等待擊發")
        print(f"     延遲設定: {self.config.get('sync_delay_ms', 0)} ms")
        print("     輸入 'go' 開始 | 'q' 取消")
        print("!" * 50)
        
        trigger = input("\n🚀 指令: ").lower()
        if trigger != 'go':
            print("🛑 已取消")
            time.sleep(1)
            self.panel.start()
            return
        
        for tid in self.selected_targets:
            self.panel.update_device(tid, status="播放中")
        
        self.panel.start(interactive=True)
        
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
        
        print("\n[控制提示] SPACE=暫停/繼續 | S=停止 | Q=退出")
        
        import select
        import sys
        
        while self.is_playing:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                key = sys.stdin.read(1).lower()
                
                if key == ' ':
                    with self.play_lock:
                        self.is_paused = not self.is_paused
                        if self.is_paused:
                            self.send_pkt(self.selected_targets, 0x3003, {})
                            for tid in self.selected_targets:
                                self.panel.update_device(tid, status="暫停")
                        else:
                            self.send_pkt(self.selected_targets, 0x3004, {})
                            for tid in self.selected_targets:
                                self.panel.update_device(tid, status="播放中")
                
                elif key == 's':
                    self.stop_all()
                    break
                
                elif key == 'q':
                    self.stop_all()
                    break
            
            time.sleep(0.1)
        
        for tid in self.selected_targets:
            self.panel.update_device(tid, status="待機")
        
        time.sleep(1)
    
    def _start_audio_stream(self, file_path):
        """啟動音訊流 (修復版)"""
        global mixer
        self.is_playing = True
        self.is_paused = False
        
        def _play_task():
            try:
                if AUDIO_MODE == 'miniaudio':
                    with miniaudio.PlaybackDevice() as device:
                        stream = miniaudio.stream_file(file_path)
                        device.start(stream)
                        
                        while device.is_active and self.running and self.is_playing:
                            while self.is_paused and self.is_playing:
                                time.sleep(0.1)
                            time.sleep(0.1)
                        
                        device.stop()
                
                elif AUDIO_MODE == 'pygame' and mixer:
                    # 🔧 確保 mixer 已初始化
                    if not mixer.get_init():
                        mixer.init()
                    
                    mixer.music.load(file_path)
                    mixer.music.play()
                    
                    while mixer.music.get_busy() and self.running and self.is_playing:
                        if self.is_paused:
                            mixer.music.pause()
                            while self.is_paused and self.is_playing:
                                time.sleep(0.1)
                            mixer.music.unpause()
                        
                        time.sleep(0.1)
                    
                    mixer.music.stop()
            
            except Exception as e:
                print(f"\n[Audio Error] {e}")
                import traceback
                traceback.print_exc()
            
            finally:
                self.is_playing = False
        
        threading.Thread(target=_play_task, daemon=True).start()
    
    def stop_all(self):
        global mixer
        self.is_playing = False
        self.is_paused = False
        
        if self.selected_targets:
            self.send_pkt(self.selected_targets, 0x3002, {})
            
            for tid in self.selected_targets:
                self.panel.update_device(tid, status="待機")
        
        if AUDIO_MODE == 'pygame' and mixer:
            try:
                if mixer.get_init():
                    mixer.music.stop()
            except:
                pass
    
    def main_loop(self):
        while self.running:
            self.panel.stop()
            ConsoleUI.clear_screen()
            ConsoleUI.show_cursor()
            
            print("\n" + "=" * 60)
            print(" 🎬 NetBus Master Control Panel")
            print("=" * 60)
            print(" 1. Select Devices     | 掃描並選擇設備")
            print(" 2. Slice Animation    | 切分動畫數據")
            print(" 3. Deploy Data        | 部署到設備 (帶監控)")
            print(" 4. Sync Play          | 同步播放 (支持暫停)")
            print(" s. STOP ALL           | 緊急停止")
            print(" q. Exit               | 退出程序")
            print("=" * 60)
            
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
# test_file_transfer.py
"""
文件傳輸完整測試工具
═══════════════════════════════════════════════════════
功能:
1. 設備發現 (UDP 廣播)
2. 文件上傳 (滑動窗口 ACK)
3. 雙階段確認 (接收 + 寫入)
4. 性能測試 (網絡速度測量)
"""

import socket
import struct
import time
import hashlib
import os
import sys
import threading
import select
import errno

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from slave.lib.proto import Proto, StreamParser
from slave.lib.schema_loader import SchemaStore
from slave.lib.schema_codec import SchemaCodec


class FileTransferTester:
    def __init__(self):
        self.store = SchemaStore(dir_path=f"{PROJECT_ROOT}/slave/schema")
        self.local_ip = self.get_local_ip()
        self.ws_port = 8000
        self.discovery_port = 9000
        
        self.devices = {}  # {device_id: {conn, parser, ...}}
        self.running = True
        
        # 傳輸狀態追蹤
        self.file_state = {
            "received_notification": False,
            "written_notification": False,
            "mode": None,
            "success": False,
            "final_sha": None,
            "error_msg": ""
        }
    
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
        """啟動 WebSocket 服務器"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # 優化緩衝區
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 512 * 1024)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
        
        s.bind(('0.0.0.0', self.ws_port))
        s.listen(10)
        
        print(f"✅ [WS Server] 監聽 0.0.0.0:{self.ws_port}")
        
        while self.running:
            try:
                conn, addr = s.accept()
                threading.Thread(
                    target=self.handle_ws_client,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except:
                break
    
    def handle_ws_client(self, conn, addr):
        """處理 WebSocket 客戶端"""
        device_id = f"TEMP_{addr[1]}"
        
        try:
            # WebSocket 握手
            header = conn.recv(1024).decode()
            if "Upgrade: websocket" not in header:
                conn.close()
                return
            
            # 提取設備 ID
            first_line = header.split('\r\n')[0]
            parts = first_line.split(' ')
            if len(parts) >= 2:
                path = parts[1].strip('/')
                if path and path != 'ws':
                    device_id = path
            
            # 發送握手響應
            resp = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
            )
            conn.send(resp.encode())
            
            # 設置非阻塞
            conn.setblocking(False)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 128 * 1024)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            
            print(f"✅ [WS] 設備已連接: {device_id}")
            
            # 註冊設備
            self.devices[device_id] = {
                "conn": conn,
                "addr": addr,
                "parser": StreamParser(),
                "ack_event": threading.Event(),
                "last_acked_offset": -1
            }
            
            # 接收數據循環
            self.device_recv_loop(device_id)
        
        except Exception as e:
            print(f"❌ [{device_id}] 錯誤: {e}")
        
        finally:
            if device_id in self.devices:
                del self.devices[device_id]
            conn.close()
            print(f"🔌 [{device_id}] 已斷開")
    
    def device_recv_loop(self, device_id):
        """設備接收循環"""
        device = self.devices[device_id]
        conn = device["conn"]
        parser = device["parser"]
        
        while self.running:
            try:
                raw = conn.recv(4096)
                if not raw:
                    break
                
                # WebSocket 解幀
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
                
                # 處理協議包
                for ver, addr_pkt, cmd, payload in parser.pop():
                    self.dispatch_command(device_id, cmd, payload)
            
            except BlockingIOError:
                time.sleep(0.01)
                continue
            
            except socket.error as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    time.sleep(0.01)
                    continue
                else:
                    break
            
            except Exception as e:
                print(f"❌ [{device_id}] 接收錯誤: {e}")
                break
    
    def dispatch_command(self, device_id, cmd, payload):
        """分發命令"""
        c_def = self.store.get(cmd)
        args = SchemaCodec.decode(c_def, payload)
        
        cmd_name = c_def.get("name", f"0x{cmd:04X}")
        
        # FILE_CHUNK_ACK
        if cmd == 0x2004:
            device = self.devices[device_id]
            device["last_acked_offset"] = args.get("offset", 0)
            device["ack_event"].set()
        
        # FILE_RECEIVED
        elif cmd == 0x2007:
            self.file_state["received_notification"] = True
            self.file_state["mode"] = "FULL_MEMORY" if args["mode"] == 1 else "ROLLING"
            print(f"\n✅ [階段 1] MCU 已接收: {args['received_bytes']} bytes")
            print(f"   模式: {self.file_state['mode']}")
        
        # FILE_WRITTEN
        elif cmd == 0x2008:
            self.file_state["written_notification"] = True
            self.file_state["success"] = (args["success"] == 1)
            self.file_state["final_sha"] = args["sha256"]
            self.file_state["error_msg"] = args.get("error_msg", "")
            
            print(f"\n✅ [階段 2] MCU 寫入完成")
            print(f"   成功: {self.file_state['success']}")
            print(f"   SHA256: {self.file_state['final_sha'].hex()}")
            if self.file_state["error_msg"]:
                print(f"   錯誤: {self.file_state['error_msg']}")
        
        else:
            print(f"📨 [{device_id}] {cmd_name}: {args}")
    
    def send_packet(self, device_id, cmd_id, args):
        """發送協議包"""
        if device_id not in self.devices:
            raise Exception(f"設備 {device_id} 未連接")
        
        device = self.devices[device_id]
        conn = device["conn"]
        
        # 構造協議包
        c_def = self.store.get(cmd_id)
        data_pkt = Proto.pack(cmd_id, SchemaCodec.encode(c_def, args))
        
        # WebSocket 封裝
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
        
        # 非阻塞發送
        total_sent = 0
        while total_sent < len(pkt):
            try:
                sent = conn.send(pkt[total_sent:])
                if sent == 0:
                    raise Exception("Socket 連接已關閉")
                total_sent += sent
            
            except BlockingIOError:
                _, writable, _ = select.select([], [conn], [], 0.1)
                if not writable:
                    raise Exception("發送超時")
                continue
    
    def broadcast_discovery(self):
        """發送廣播包"""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        payload = SchemaCodec.encode(
            self.store.get(0x1001),
            {
                "server_ip": self.local_ip,
                "ws_url": f"ws://{self.local_ip}:{self.ws_port}"
            }
        )
        
        s.sendto(Proto.pack(0x1001, payload), ('255.255.255.255', self.discovery_port))
        s.close()
        
        print(f"📡 廣播已發送 (ws://{self.local_ip}:{self.ws_port})")
    
    def upload_file(self, device_id, file_path, chunk_size=4096):
        """
        上傳文件到指定設備
        支持滑動窗口 ACK
        """
        if not os.path.exists(file_path):
            print(f"❌ 文件不存在: {file_path}")
            return False
        
        # 讀取文件
        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        file_sha = hashlib.sha256(file_data).digest()
        
        print(f"\n{'='*60}")
        print(f"📂 開始上傳: {file_path}")
        print(f"📊 文件大小: {file_size // 1024} KB")
        print(f"🔒 SHA256: {file_sha.hex()}")
        print(f"{'='*60}")
        
        # 重置狀態
        self.file_state = {
            "received_notification": False,
            "written_notification": False,
            "mode": None,
            "success": False,
            "final_sha": None,
            "error_msg": ""
        }
        
        # 🔥 階段 1: 發送 BEGIN
        print("\n[階段 1] 發送 FILE_BEGIN...")
        self.send_packet(device_id, 0x2001, {
            "file_id": 1,
            "total_size": file_size,
            "chunk_size": chunk_size,
            "sha256": file_sha,
            "path": "/test_upload.bin"
        })
        
        time.sleep(0.2)
        
        # 🔥 階段 2: 滑動窗口發送數據
        print("\n[階段 2] 發送數據塊 (滑動窗口)...")
        
        device = self.devices[device_id]
        
        INITIAL_WINDOW = 32
        MAX_WINDOW = 64
        MIN_WINDOW = 8
        
        current_window = INITIAL_WINDOW
        pending_acks = {}
        send_offset = 0
        confirmed_offset = 0
        last_ack_time = time.time()
        
        start_time = time.time()
        last_print = start_time
        
        while confirmed_offset < file_size:
            now = time.time()
            
            # 批量發送
            while len(pending_acks) < current_window and send_offset < file_size:
                chunk = file_data[send_offset : send_offset + chunk_size]
                
                try:
                    self.send_packet(device_id, 0x2002, {
                        "file_id": 1,
                        "offset": send_offset,
                        "data": chunk
                    })
                    
                    pending_acks[send_offset] = now
                    send_offset += len(chunk)
                
                except BlockingIOError:
                    break
            
            # 批量收集 ACK
            ack_deadline = time.time() + 0.01
            
            while time.time() < ack_deadline and len(pending_acks) > 0:
                if device["ack_event"].wait(timeout=0.002):
                    device["ack_event"].clear()
                    
                    acked_offset = device.get("last_acked_offset", -1)
                    
                    if acked_offset in pending_acks:
                        del pending_acks[acked_offset]
                        
                        if acked_offset >= confirmed_offset:
                            confirmed_offset = acked_offset + chunk_size
                        
                        last_ack_time = now
                        
                        if current_window < MAX_WINDOW:
                            current_window = min(MAX_WINDOW, current_window + 2)
                else:
                    break
            
            # 定期打印進度
            if now - last_print > 1.0:
                elapsed = now - start_time
                speed = (confirmed_offset / 1024) / elapsed if elapsed > 0 else 0
                progress = (confirmed_offset / file_size) * 100
                
                print(f"📊 進度: {progress:5.1f}% | "
                      f"速度: {speed:6.1f} KB/s | "
                      f"窗口: {current_window} | "
                      f"未確認: {len(pending_acks)}")
                
                last_print = now
            
            # 超時重傳
            if now - last_ack_time > 2.0 and len(pending_acks) > 0:
                if current_window > MIN_WINDOW:
                    current_window = max(MIN_WINDOW, int(current_window * 0.75))
                
                oldest_offset = min(pending_acks.keys())
                chunk = file_data[oldest_offset : oldest_offset + chunk_size]
                
                self.send_packet(device_id, 0x2002, {
                    "file_id": 1,
                    "offset": oldest_offset,
                    "data": chunk
                })
                
                pending_acks[oldest_offset] = now
                last_ack_time = now
        
        elapsed_total = time.time() - start_time
        avg_speed = (file_size / 1024) / elapsed_total
        
        print(f"\n✅ 數據發送完成")
        print(f"   總耗時: {elapsed_total:.2f} 秒")
        print(f"   平均速度: {avg_speed:.1f} KB/s")
        
        # 🔥 階段 3: 發送 END
        print(f"\n[階段 3] 發送 FILE_END...")
        self.send_packet(device_id, 0x2003, {"file_id": 1})
        
        # 等待接收確認
        print("⏳ 等待 MCU 確認接收...")
        timeout = 10.0
        start_wait = time.time()
        
        while not self.file_state["received_notification"]:
            if time.time() - start_wait > timeout:
                print("❌ 超時: 未收到接收確認")
                return False
            time.sleep(0.1)
        
        # 🔥 階段 4: 等待寫入完成
        print("\n[階段 4] 等待 Flash 寫入...")
        timeout = 60.0
        start_wait = time.time()
        
        while not self.file_state["written_notification"]:
            if time.time() - start_wait > timeout:
                print("❌ 超時: 未收到寫入確認")
                return False
            time.sleep(0.1)
        
        # 最終驗證
        print(f"\n{'='*60}")
        print("傳輸完成")
        print(f"{'='*60}")
        print(f"本地 SHA256: {file_sha.hex()}")
        print(f"遠程 SHA256: {self.file_state['final_sha'].hex()}")
        
        if file_sha == self.file_state["final_sha"]:
            print("✅ SHA256 校驗通過")
            return True
        else:
            print("❌ SHA256 校驗失敗")
            return False
    
    def run(self):
        """主運行函數"""
        print("╔════════════════════════════════════════╗")
        print("║  文件傳輸測試工具 v2.0                ║")
        print("║  支持雙階段確認與滑動窗口              ║")
        print("╚════════════════════════════════════════╝")
        print(f"\n本機 IP: {self.local_ip}\n")
        
        # 啟動 WebSocket 服務器
        ws_thread = threading.Thread(target=self.start_ws_server, daemon=True)
        ws_thread.start()
        
        time.sleep(1)
        
        # 發送廣播
        self.broadcast_discovery()
        
        time.sleep(2)
        
        # 選擇設備
        if not self.devices:
            print("❌ 無設備連接")
            return
        
        print(f"\n📋 已連接設備 ({len(self.devices)}):")
        device_list = list(self.devices.keys())
        for i, dev_id in enumerate(device_list, 1):
            print(f"  {i}. {dev_id}")
        
        try:
            choice = int(input("\n👉 選擇設備編號: ")) - 1
            if choice < 0 or choice >= len(device_list):
                print("❌ 無效選擇")
                return
            
            target_device = device_list[choice]
        except:
            print("❌ 無效輸入")
            return
        
        # 選擇文件
        print("\n測試選項:")
        print("1. 上傳指定文件")
        print("2. 生成隨機測試文件")
        
        test_choice = input("\n👉 請選擇 (1/2): ").strip()
        
        if test_choice == "1":
            file_path = input("請輸入文件路徑: ").strip()
        else:
            size_kb = int(input("請輸入文件大小 (KB, 默認 1024): ").strip() or "1024")
            file_path = "test_random.bin"
            
            print(f"⚙️ 生成 {size_kb} KB 隨機文件...")
            with open(file_path, "wb") as f:
                f.write(os.urandom(size_kb * 1024))
            print(f"✅ 已生成: {file_path}")
        
        # 開始上傳
        success = self.upload_file(target_device, file_path)
        
        if success:
            print("\n🎉 測試成功!")
        else:
            print("\n❌ 測試失敗")


if __name__ == "__main__":
    tester = FileTransferTester()
    try:
        tester.run()
    except KeyboardInterrupt:
        print("\n\n🛑 用戶中斷")
    finally:
        tester.running = False
        print("\n再見! 👋")
import hashlib
import ubinascii
import os, gc, json
from lib.sys_bus import bus

class FileRx:
    """
    高性能文件接收組件 - 支援分片寫入與 SHA256 流式校驗
    """
    def __init__(self):
        self.reset()
        self.last_sha_hex = "" # 儲存最後一次成功或失敗的哈希計算結果

    def ensure_dir(self, path):
        """檢查並創建目錄路徑"""
        parts = path.split('/')
        curr = ""
        for p in parts[:-1]: # 最後一個是檔名，跳過
            if not p: continue
            curr += "/" + p
            try:
                os.mkdir(curr)
            except OSError:
                pass # 已存在則忽略

    def get_fs_tree_and_save(self, root_path, out_path):
        """
        遍歷文件系統，計算每個文件的 SHA256，並流式寫入 JSON。
        """
        self.ensure_dir(out_path)
        
        # 使用本地引用加速
        compute_sha = self.sha256_digest_stream_from_file
        
        
        with open(out_path, "w") as f:
            f.write('{"root":"%s","entries":[' % root_path)
            
            first = True
            # 使用 stack 進行深度優先遍歷 (避免遞歸消耗 stack 空間)
            stack = [root_path]
            
            while stack:
                curr_dir = stack.pop()
                try:
                    # ilistdir 返回 (name, type, inode, [size])
                    # type: 0x4000 是目錄, 0x8000 是文件
                    for entry in os.ilistdir(curr_dir):
                        name = entry[0]
                        etype = entry[1]
                        
                        # 構建完整路徑
                        full_path = curr_dir + ("" if curr_dir.endswith("/") else "/") + name
                        
                        if not first: f.write(",")
                        first = False
                        
                        if etype == 0x4000: # Directory
                            f.write('\n{"p":"%s","n":"%s","t":"d"}' % (curr_dir, name))
                            stack.append(full_path)
                        else: # File
                            # 核心要求：計算 SHA256
                            sha_bytes = compute_sha(full_path)
                            sha_hex = ubinascii.hexlify(sha_bytes).decode()
                            
                            try:
                                size = os.stat(full_path)[6]
                            except:
                                size = 0
                                
                            f.write('\n{"p":"%s","n":"%s","t":"f","s":%d,"sha":"%s"}' % 
                                    (curr_dir, name, size, sha_hex))
                            
                        # 每處理一個文件就釋放一次記憶體
                        gc.collect()
                        
                except Exception as e:
                    print(f"Read dir error {curr_dir}: {e}")
                    
            f.write("\n]}")

    def get_extreme_bufsize(self):
        """
        極限性能導向的緩衝區計算
        目標：尋找 32KB - 128KB 之間的平衡點
        """
        gc.collect()
        free_ram = gc.mem_free()
        
        # 策略：
        # 1. 至少保留 32KB 給系統維持運作 (避免執行時期的臨時分配失敗)
        # 2. 緩衝區設為可用 RAM 的 25%
        # 3. 硬性限制在 128KB (因為超過此值，SHA256 運算與 I/O 的重疊增益將消失)
        
        suggested = (free_ram - 32 * 1024) // 4
        
        # 對齊 4KB (檔案系統 Cluster 大小)，這能確保讀取地址對齊，提高 DMA 效率
        target = (suggested // 4096) * 4096
        
        # 限制在 [4KB, 128KB] 區間
        return max(4096, min(target, 128 * 1024))

    def sha256_digest_stream_from_file(self, path):
        """
        串流計算文件 SHA256，避免將大文件一次性載入記憶體導致 OOM。
        使用 memoryview 優化字節切片效能。
        """
        bufsize = self.get_extreme_bufsize()

        # 預先分配（如果 RAM 充足，這會嘗試在 SRAM 或 PSRAM 分配）
        buf = bytearray(bufsize)
        mv = memoryview(buf)
        h = hashlib.sha256()

        try:
            # 使用本地變量引用以優化 lookup 速度 (資深程序員的老技巧)
            update = h.update
            readinto = open(path, "rb").readinto
            
            # 這裡不使用 with 語句，而是手動控制以獲取極微小的速度提升
            f = open(path, "rb")
            _readinto = f.readinto
            
            while True:
                n = _readinto(buf)
                if n == 0:
                    break
                if n == bufsize:
                    update(mv)
                else:
                    update(mv[:n])
            f.close()
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            del buf
            gc.collect()
            
        return h.digest()


    def reset(self):
        """重置接收狀態"""
        self.active = False
        self.file_id = 0
        self.total = 0
        self.path = None
        self.fp = None
        self.written = 0
        self.sha_expect = None
        self.last_error = None

    def _close(self):
        """安全關閉文件句柄，並強制刷入磁盤"""
        if self.fp:
            try:
                self.fp.flush()
                # 某些 MicroPython 端口支援 os.sync()
                if hasattr(os, 'sync'):
                    os.sync()
                self.fp.close()
            except:
                pass
        self.fp = None

    def begin(self, args: dict) -> bool:
        """
        FILE_BEGIN (0x2001) 處理邏輯
        """
        self._close()
        self.reset()
        
        self.file_id = int(args.get("file_id", 0))
        self.total = int(args.get("total_size", 0))
        self.path = bus.get_service("data_Phat") + args.get("path")
        self.sha_expect = args.get("sha256")
        
        if not self.path or not self.sha_expect:
            self.last_error = "MISSING_PATH_OR_SHA"
            return False

        try:
            # 以 'wb' 模式開啟會自動清空舊文件
            # 對於 ESP32-P4，直接順序寫入比頻繁 seek 預分配更快
            self.fp = open(self.path, "wb")
            self.active = True
            return True
        except Exception as e:
            self.last_error = f"OPEN_FAIL: {e}"
            return False

    def chunk(self, args: dict) -> bool:
        """
        FILE_CHUNK (0x2002) 處理邏輯
        支持斷點續傳地址定位，但推薦順序發送以獲得最高效能。
        """
        if not self.active or not self.fp:
            self.last_error = "NO_ACTIVE_SESSION"
            return False
        
        # 檢查 file_id 是否匹配當前任務
        if int(args.get("file_id", 0)) != self.file_id:
            return False

        off = int(args.get("offset", 0))
        data = args.get("data", b"")
        
        try:
            # 只有當 offset 不在當前磁頭位置時才執行 seek
            if off != self.written:
                self.fp.seek(off)
            
            self.fp.write(data)
            self.written = off + len(data)
            return True
        except Exception as e:
            self.last_error = f"WRITE_FAIL: {e}"
            self.active = False # 發生物理錯誤時解除激活
            return False

    def end(self, args: dict) -> bool:
        """
        FILE_END (0x2003) 處理邏輯
        執行最終的哈希驗證並關閉任務。
        """
        if not self.active:
            return False
            
        # 1. 先關閉文件，確保所有數據已從緩存刷入 Flash
        self._close()
        
        try:
            # 2. 計算實際寫入文件的哈希值
            got_digest = self.sha256_digest_stream_from_file(self.path)
            self.last_sha_hex = ubinascii.hexlify(got_digest).decode()
            
            # 3. 雙向對應
            if got_digest == self.sha_expect:
                self.active = False
                return True
            else:
                exp_hex = ubinascii.hexlify(self.sha_expect).decode()
                self.last_error = f"SHA_MISMATCH got {self.last_sha_hex}"
                self.active = False
                return False
        except Exception as e:
            self.last_error = f"VERIFY_ERR: {e}"
            self.active = False
            return False
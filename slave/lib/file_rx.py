import hashlib
import ubinascii
import os, gc, json
from lib.sys_bus import bus
from lib.memory_manager import MemoryManager

class FileRx:
    """
    高性能文件接收組件 - 支援分片寫入與 SHA256 流式校驗
    使用 MemoryManager 進行動態緩衝區分配
    新增: 4KB 寫入緩衝 (Write Buffering) 以優化 Flash 壽命與效能
    """
    
    # Flash Sector Size 通常為 4096，以此為緩衝單位最高效
    WRITE_BUF_SIZE = 16384 # 16KB

    def __init__(self, buf_size=None):
        self.reset()
        self.last_sha_hex = "" 
        self.mem_mgr = MemoryManager.get() 
        self.hasher = None # 流式校驗器

        # 允許外部傳入 buf_size，否則使用默認 16KB
        if buf_size: self.WRITE_BUF_SIZE = buf_size
        
        # 預分配寫入緩衝區 (固定 RAM 開銷)
        self.w_buf = bytearray(self.WRITE_BUF_SIZE)
        self.w_view = memoryview(self.w_buf)
        self.w_pos = 0  # 緩衝區當前指針

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
        
        # 為了避免頻繁的 GC，我們在這裡使用一個較大的緩衝區來讀取目錄
        # 但 os.ilistdir 已經很高效，所以主要是控制 SHA 計算時的內存
        
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

    def sha256_digest_stream_from_file(self, path):
        """
        串流計算文件 SHA256，針對大內存 (PSRAM) 優化。
        動態租用「最大可用」緩衝區，一次吞吐數 MB，大幅減少 I/O 調用次數。
        """
        # 嘗試租用最大緩衝區 (預設上限 16MB)
        buf = self.mem_mgr.rent_max(hard_limit=16*1024*1024)
        bufsize = len(buf)
        mv = memoryview(buf)
        h = hashlib.sha256()

        try:
            # 使用本地變量引用以優化 lookup 速度
            update = h.update
            
            f = open(path, "rb")
            readinto = f.readinto
            
            while True:
                n = readinto(buf)
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
            del mv
            gc.collect()
            
        return h.digest()

    def reset(self):
        """重置接收狀態"""
        self.active = False
        self.file_id = 0
        self.total = 0
        self.path = None
        self.fp = None
        self.written = 0      # 邏輯寫入位置 (包含 buffer 中的數據)
        self.w_pos = 0        # Buffer 指針重置
        self.sha_expect = None
        self.last_error = None
        self.hasher = None

    def _flush(self):
        """將緩衝區數據寫入物理磁碟"""
        if self.fp and self.w_pos > 0:
            try:
                # 寫入有效部分的數據
                self.fp.write(self.w_view[:self.w_pos])
                self.w_pos = 0
            except Exception as e:
                self.last_error = f"FLUSH_FAIL: {e}"
                print(self.last_error)
                raise e

    def _close(self):
        """安全關閉文件句柄，並強制刷入磁盤"""
        if self.fp:
            try:
                self._flush()  # 關鍵：關閉前清空緩衝
                self.fp.flush() # 系統層 flush
                if hasattr(os, 'sync'):
                    os.sync()
                self.fp.close()
            except:
                pass
        self.fp = None
        self.w_pos = 0

    def begin(self, args: dict) -> bool:
        """FILE_BEGIN (0x2001)"""
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
            self.fp = open(self.path, "wb")
            self.active = True
            self.hasher = hashlib.sha256() # 初始化流式校驗
            return True
        except Exception as e:
            self.last_error = f"OPEN_FAIL: {e}"
            return False

    def chunk(self, args: dict) -> bool:
        """
        FILE_CHUNK (0x2002) - 帶緩衝寫入
        """
        if not self.active or not self.fp:
            self.last_error = "NO_ACTIVE_SESSION"
            return False
        
        if int(args.get("file_id", 0)) != self.file_id:
            return False

        off = int(args.get("offset", 0))
        data = args.get("data", b"")
        d_len = len(data)
        
        if d_len == 0:
            return True

        # 流式校驗
        if self.hasher:
            self.hasher.update(data)

        try:
            # 檢查是否發生亂序或 Seek (Offset 不等於當前邏輯結尾)
            # self.written 追蹤的是「邏輯上」已經處理到的字節位置
            if off != self.written:
                # 發生跳躍，必須先將手頭上的緩衝寫入，才能移動磁頭
                self._flush()
                self.fp.seek(off)
                self.written = off

            # 數據寫入邏輯
            
            # Case 0: 快速通道 (數據很大且緩衝區為空)
            # 如果數據大於等於 Buffer 大小，且 Buffer 為空，直接寫入文件，跳過 RAM 拷貝
            if self.w_pos == 0 and d_len >= self.WRITE_BUF_SIZE:
                # 如果不是整數倍，我們可以寫入大部分，剩下的放緩衝
                # 但為了簡單，這裡直接全部寫入
                self.fp.write(data)
                self.written += d_len
                return True

            # Case 1: 數據可以完全塞入剩餘緩衝區
            if self.w_pos + d_len <= self.WRITE_BUF_SIZE:
                self.w_view[self.w_pos : self.w_pos + d_len] = data
                self.w_pos += d_len
                
                # [優化] 如果剛好填滿，立即 Flush
                if self.w_pos == self.WRITE_BUF_SIZE:
                    self._flush()
            
            # Case 2: 數據大於剩餘空間 -> 先填滿緩衝區並 Flush，剩餘的再處理
            else:
                current_data_ptr = 0
                remaining = d_len
                
                while remaining > 0:
                    # 計算這次能搬多少
                    space = self.WRITE_BUF_SIZE - self.w_pos
                    take = min(remaining, space)
                    
                    self.w_view[self.w_pos : self.w_pos + take] = data[current_data_ptr : current_data_ptr + take]
                    self.w_pos += take
                    current_data_ptr += take
                    remaining -= take
                    
                    # 如果滿了就 Flush
                    if self.w_pos == self.WRITE_BUF_SIZE:
                        self._flush()

            # 更新邏輯寫入位置
            self.written += d_len
            return True

        except Exception as e:
            self.last_error = f"WRITE_FAIL: {e}"
            self.active = False
            return False

    def end(self, args: dict) -> bool:
        """FILE_END (0x2003)"""
        if not self.active:
            return False
            
        # 1. Close 會自動觸發 _flush
        self._close()
        
        try:
            # 2. 快速校驗：直接獲取流式計算結果
            if self.hasher:
                got_digest = self.hasher.digest()
                self.hasher = None # 釋放
            else:
                # 備用方案：如果中間有 Seek 導致流式校驗失效，則回退到全文件讀取
                # 但目前 chunk 實現不支持 seek 時回退 hasher，所以假設順序寫入
                got_digest = self.sha256_digest_stream_from_file(self.path)
                
            self.last_sha_hex = ubinascii.hexlify(got_digest).decode()
            
            if got_digest == self.sha_expect:
                self.active = False
                return True
            else:
                self.last_error = f"SHA_MISMATCH got {self.last_sha_hex}"
                self.active = False
                return False
        except Exception as e:
            self.last_error = f"VERIFY_ERR: {e}"
            self.active = False
            return False

from lib.sys_bus import bus
from lib.file_hub import FileRxHub
from lib.proto import Proto
from lib.schema_codec import SchemaCodec
import os

class FileRx:
    """
    FileRx V2 (Turbo)
    Core 0 端文件接收器，負責將數據快速搬運到 FileRxHub
    """
    def __init__(self, app):
        self.app = app
        # 初始化 File Hub
        self.hub = FileRxHub(size=4096, num_buffers=2)
        bus.register_service("file_rx", self.hub)
        
        # 註冊命令處理
        app.disp.on(0x2001, self.on_begin)
        app.disp.on(0x2002, self.on_chunk)
        app.disp.on(0x2003, self.on_end)
        app.disp.on(0x2005, self.on_query)
        
        self.current_fid = 0
        self.save_mode = 0
        self.active = False
        self.last_offset = 0

    def send_ack(self, ctx, fid, offset, status):
        """發送 ACK (0x2004)"""
        cmd_def = self.app.store.get(0x2004)
        payload = {
            "file_id": fid,
            "offset": offset,
            "status": status # 0=OK, 1=Retry, 2=Error
        }
        data = SchemaCodec.encode(cmd_def, payload)
        ctx["send"](Proto.pack(0x2004, data))

    def on_begin(self, ctx, args):
        """0x2001 FILE_BEGIN"""
        fid = args["file_id"]
        total = args["total_size"]
        path = args["path"]
        save_mode = args.get("save_mode", 1) # 默認保存
        
        print(f"📂 [FileRx] Begin: {path} ({total} bytes) Mode={save_mode}")
        
        # 1. 檢查是否需要覆蓋 (save_mode=1)
        if save_mode == 1:
            try:
                # 如果文件存在且大小相同，嘗試直接覆蓋 (其實直接用 'wb' 就行)
                # 這裡主要是為了檢查路徑合法性
                # TODO: 檢查剩餘空間
                pass
            except Exception as e:
                print(f"❌ Path Error: {e}")
                self.send_ack(ctx, fid, 0, 2) # Error
                return

        # 2. 初始化 Hub 會話 (分配內存)
        if not self.hub.start_session(args):
            print("❌ OOM: Cannot allocate buffer")
            self.send_ack(ctx, fid, 0, 2)
            return

        self.current_fid = fid
        self.save_mode = save_mode
        self.active = True
        self.last_offset = 0
        
        # 通知 Core 1 準備接收 (通過 Bus 狀態)
        bus.shared["file_session"] = {
            "state": "active",
            "file_id": fid,
            "path": path,
            "save_mode": save_mode,
            "total": total,
            "sha256": args["sha256"]
        }
        
        self.send_ack(ctx, fid, 0, 0) # OK

    def on_chunk(self, ctx, args):
        """0x2002 FILE_CHUNK"""
        if not self.active or args["file_id"] != self.current_fid:
            return # 忽略無效包

        data = args["data"]
        offset = args["offset"]
        
        # 1. 寫入 Hub (極速操作)
        # 注意: Hub 會自動處理雙緩衝切換，如果滿了會返回 False
        if self.hub.write_from(data):
            # 成功寫入 RAM
            self.hub.update_sha256(data) # 更新流式 Hash
            self.last_offset = offset + len(data)
            
            # 檢查 Hub 是否有數據可供 Core 1 消費 (Dirty)
            if self.hub.dirty:
                # 觸發 Core 1 (通過 Bus 事件或輪詢)
                # 在此架構下，Core 1 會輪詢 Hub 狀態
                pass
                
            self.send_ack(ctx, self.current_fid, self.last_offset, 0)
        else:
            # Hub 滿了 (Core 1 寫入太慢)
            # 通知 PC 重試/流控
            print("⚠️ [FileRx] Hub Full/Busy")
            self.send_ack(ctx, self.current_fid, offset, 1) # Retry

    def on_end(self, ctx, args):
        """0x2003 FILE_END"""
        if not self.active: return
        
        fid = args["file_id"]
        print(f"📂 [FileRx] End Recv: {fid}")
        
        # 提交最後一塊數據
        self.hub.commit() 
        
        # 通知 Core 1 結束
        bus.shared["file_session"]["state"] = "finishing"
        
        # Core 0 任務完成，剩下的交給 Core 1
        self.active = False
        
        # 這裡不發 ACK，等 Core 1 寫完/驗證完再由 Core 1 或輪詢發送最終結果
        # 或者此時發送一個 "接收完成，正在寫入" 的 ACK
        self.send_ack(ctx, fid, self.last_offset, 0)

    def on_query(self, ctx, args):
        """0x2005 FILE_QUERY"""
        path = args["path"]
        # TODO: 實現索引查詢或即時檢查
        # 暫時返回不存在
        cmd_def = self.app.store.get(0x2006)
        payload = {
            "exists": 0,
            "sha256": bytes(32),
            "path": path
        }
        data = SchemaCodec.encode(cmd_def, payload)
        ctx["send"](Proto.pack(0x2006, data))

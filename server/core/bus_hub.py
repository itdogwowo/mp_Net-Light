# server/core/bus_hub.py
import hashlib
import time
from .protocol import proto_mgr
import logging

logger = logging.getLogger(__name__)

class MCUCommandHub:
    def __init__(self, bus):
        self.bus = bus  # 持有 NetBus 實例
        self.ack_event = None # 用於同步文件上傳的事件 (如果你在 Django 使用多執行緒)

    # --- 1. 發現與連接測試 ---
    def test_handshake(self):
        """發送一個心跳或狀態查詢來測試連接"""
        pkt = proto_mgr.pack(0x1101, {"flags": 1, "detail": 0})
        self.bus.write(pkt)

    # --- 2. 串流控制 (從 PCTestTool 遷移) ---
    def stream_control(self, start=True, fps=40, mode="network"):
        cmd = 0x3001 if start else 0x3002
        payload = {"fps": fps, "mode": mode} if start else {}
        pkt = proto_mgr.pack(cmd, payload)
        self.bus.write(pkt)
        logger.info(f"[{self.bus.label}] Stream {'Started' if start else 'Stopped'}")

    # --- 3. 檔案上傳 (從 PCTestTool 遷移) ---
    def upload_file(self, local_data, remote_path, chunk_size=1024):
        """
        將 PCTestTool 的上傳邏輯遷移至此
        注意：Django 環境建議異步或使用線程處理大文件，避免阻塞主循環
        """
        sha_bytes = hashlib.sha256(local_data).digest()
        f_id = int(time.time()) & 0xFFFF # 隨機 file_id
        
        # 1. FILE_BEGIN (0x2001)
        begin_pkt = proto_mgr.pack(0x2001, {
            "file_id": f_id,
            "total_size": len(local_data),
            "chunk_size": chunk_size,
            "sha256": sha_bytes,
            "path": remote_path
        })
        self.bus.write(begin_pkt)
        time.sleep(0.1) # 給 MCU 準備時間
        
        # 2. FILE_CHUNK (0x2002)
        for offset in range(0, len(local_data), chunk_size):
            chunk = local_data[offset : offset + chunk_size]
            chunk_pkt = proto_mgr.pack(0x2002, {
                "file_id": f_id,
                "offset": offset,
                "data": chunk
            })
            self.bus.write(chunk_pkt)
            # 這裡暫時使用簡易延時，未來可對接更複雜的 ACK 停等機制
            time.sleep(0.02) 
        
        # 3. FILE_END (0x2003)
        end_pkt = proto_mgr.pack(0x2003, {"file_id": f_id})
        self.bus.write(end_pkt)
        logger.info(f"[{self.bus.label}] Uploaded {remote_path} ({len(local_data)} bytes)")
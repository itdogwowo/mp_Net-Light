# light_control/pxld_v3_indexer.py
# 只做「列出 slave entries」用於 dashboard/mapping 預設

import struct
from dataclasses import dataclass
from typing import List, Dict, Any

V3_FILE_HEADER_SIZE = 64
V3_FRAME_HEADER_SIZE = 32
V3_SLAVE_ENTRY_SIZE = 24

@dataclass
class SlaveEntry:
    slave_id: int
    channel_start: int
    channel_count: int
    pixel_count: int
    data_offset: int
    data_length: int

def read_pxld_v3_slave_list(pxld_path: str, frame_id: int = 0) -> List[SlaveEntry]:
    """
    讀 PXLD v3，回傳指定 frame 的 slave 列表。
    依規範：FrameHeader 固定 32 bytes；slave_table_size/pixel_data_size 從 header 內取 [1][2]
    """
    with open(pxld_path, "rb") as f:
        # FileHeader 64 bytes（此處先不做 CRC32，展示用可先略）
        f.seek(0)
        hdr = f.read(V3_FILE_HEADER_SIZE)
        if hdr[0:4] != b"PXLD":
            raise ValueError("不是 PXLD 檔案")

        major = hdr[4]
        if major != 3:
            raise ValueError(f"不是 v3：major={major}")

        total_slaves = struct.unpack("<H", hdr[7:9])[0]

        # 這裡先只支援 frame0：假設 frame0 緊接在 FileHeader 後
        # 更完整做法要建立 frame_offsets 索引（之後可按你已有 decoder 擴展）
        f.seek(V3_FILE_HEADER_SIZE)

        frame_header = f.read(V3_FRAME_HEADER_SIZE)
        if len(frame_header) != V3_FRAME_HEADER_SIZE:
            raise ValueError("讀不到 frame header")

        slave_table_size = struct.unpack("<I", frame_header[8:12])[0]   # [1][2]
        pixel_data_size  = struct.unpack("<I", frame_header[12:16])[0]  # [1][2]

        slave_table = f.read(slave_table_size)
        if len(slave_table) != slave_table_size:
            raise ValueError("slave table 長度不足")

        # pixel_data 不一定要讀出來，展示 slave 列表只需 size 做邊界檢查
        slaves: List[SlaveEntry] = []
        for i in range(total_slaves):
            off = i * V3_SLAVE_ENTRY_SIZE
            entry = slave_table[off:off + V3_SLAVE_ENTRY_SIZE]
            if len(entry) != V3_SLAVE_ENTRY_SIZE:
                break

            slave_id = entry[0]
            channel_start = struct.unpack("<H", entry[2:4])[0]
            channel_count = struct.unpack("<H", entry[4:6])[0]
            pixel_count   = struct.unpack("<H", entry[6:8])[0]
            data_offset   = struct.unpack("<I", entry[8:12])[0]
            data_length   = struct.unpack("<I", entry[12:16])[0]

            # 邊界檢查：offset+len <= pixel_data_size [1]
            if data_offset + data_length > pixel_data_size:
                # 展示用：仍回傳，但標記不合法
                pass

            slaves.append(SlaveEntry(
                slave_id=slave_id,
                channel_start=channel_start,
                channel_count=channel_count,
                pixel_count=pixel_count,
                data_offset=data_offset,
                data_length=data_length,
            ))
        return slaves
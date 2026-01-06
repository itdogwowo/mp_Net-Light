# light_control/pxld_v3_decoder.py
# PXLD v3：只做 server 端 dashboard/mapping 需要的解析（info + frame0 slave table）
# 解析流程：Header->CRC32->Index->Frame [1]
# FrameHeader: slave_table_size@8..12, pixel_data_size@12..16 [2]

from __future__ import annotations
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any

V3_FILE_HEADER_SIZE = 64
V3_FRAME_HEADER_SIZE = 32
V3_SLAVE_ENTRY_SIZE = 24

@dataclass
class PxldInfo:
    magic: str
    major: int
    minor: int
    fps: int
    total_slaves: int
    total_frames: int
    total_pixels: int
    frame_header_size: int
    slave_entry_size: int
    udp_port: int
    checksum_type: int
    file_crc32: int
    crc32_ok: bool

@dataclass
class SlaveEntry:
    slave_id: int
    flags: int
    channel_start: int
    channel_count: int
    pixel_count: int
    data_offset: int
    data_length: int
    valid_bounds: bool

class PXLDv3:
    def __init__(self, filepath: str):
        self.filepath = str(filepath)
        self.path = Path(filepath)
        self.info: PxldInfo | None = None
        self.frame_offsets: List[int] = []
        self._open_and_index()

    # -------- CRC32 --------
    def _verify_crc32(self, header_crc32: int, checksum_type: int) -> bool:
        # checksum_type == 0 => no checksum
        if checksum_type == 0:
            return True

        # 簡化：用 zlib.crc32 計算整檔（從 offset 27 開始的細節若你規格不同可再調）
        # 但我們仍會把結果展示在 UI；失敗就直接標記 false
        data = self.path.read_bytes()
        calc = zlib.crc32(data) & 0xFFFFFFFF
        return calc == header_crc32

    # -------- parse header + index --------
    def _open_and_index(self):
        with open(self.filepath, "rb") as f:
            header = f.read(V3_FILE_HEADER_SIZE)
            if len(header) != V3_FILE_HEADER_SIZE:
                raise ValueError("FileHeader 長度不足")

            magic = header[0:4].decode("ascii", errors="ignore")
            if magic != "PXLD":
                raise ValueError("不是有效的 PXLD 檔案")

            major = header[4]
            minor = header[5]
            if major != 3:
                raise ValueError(f"不支援版本 {major}.{minor}（只支援 v3）")

            fps = header[6]
            total_slaves = struct.unpack("<H", header[7:9])[0]
            total_frames = struct.unpack("<I", header[9:13])[0]
            total_pixels = struct.unpack("<I", header[13:17])[0]
            frame_header_size = struct.unpack("<H", header[17:19])[0]
            slave_entry_size = struct.unpack("<H", header[19:21])[0]
            udp_port = struct.unpack("<H", header[21:23])[0]
            file_crc32 = struct.unpack("<I", header[23:27])[0]
            checksum_type = header[27]

            crc_ok = self._verify_crc32(file_crc32, checksum_type)

            # 驗證清單：frame_header_size=32, slave_entry_size=24 [1]
            if frame_header_size != V3_FRAME_HEADER_SIZE:
                raise ValueError(f"frame_header_size={frame_header_size} 非 32（v3）")
            if slave_entry_size != V3_SLAVE_ENTRY_SIZE:
                raise ValueError(f"slave_entry_size={slave_entry_size} 非 24（v3）")

            self.info = PxldInfo(
                magic=magic, major=major, minor=minor,
                fps=fps, total_slaves=total_slaves, total_frames=total_frames,
                total_pixels=total_pixels,
                frame_header_size=frame_header_size,
                slave_entry_size=slave_entry_size,
                udp_port=udp_port,
                checksum_type=checksum_type,
                file_crc32=file_crc32,
                crc32_ok=crc_ok,
            )

            # 建立 frame_offsets 索引：offset += 32 + slave_table_size + pixel_data_size [1][2]
            self.frame_offsets = []
            cur = V3_FILE_HEADER_SIZE
            for _ in range(total_frames):
                self.frame_offsets.append(cur)
                f.seek(cur)
                frame_header = f.read(V3_FRAME_HEADER_SIZE)
                if len(frame_header) != V3_FRAME_HEADER_SIZE:
                    break
                slave_table_size = struct.unpack("<I", frame_header[8:12])[0]   # [2]
                pixel_data_size = struct.unpack("<I", frame_header[12:16])[0]  # [2]

                # 驗證：slave_table_size = total_slaves * 24 [1]
                expect_st = total_slaves * V3_SLAVE_ENTRY_SIZE
                if slave_table_size != expect_st:
                    raise ValueError(f"slave_table_size={slave_table_size} != total_slaves*24({expect_st})")

                cur += V3_FRAME_HEADER_SIZE + slave_table_size + pixel_data_size  # [2]

    # -------- public: info + slave table --------
    def get_info_dict(self) -> Dict[str, Any]:
        assert self.info is not None
        d = self.info.__dict__.copy()
        d["version"] = f"{self.info.major}.{self.info.minor}"
        return d

    def get_frame0_slaves(self) -> List[SlaveEntry]:
        assert self.info is not None
        with open(self.filepath, "rb") as f:
            if not self.frame_offsets:
                return []
            f.seek(self.frame_offsets[0])

            frame_header = f.read(V3_FRAME_HEADER_SIZE)
            slave_table_size = struct.unpack("<I", frame_header[8:12])[0]   # [2]
            pixel_data_size = struct.unpack("<I", frame_header[12:16])[0]  # [2]

            slave_table = f.read(slave_table_size)
            slaves: List[SlaveEntry] = []

            for i in range(self.info.total_slaves):
                off = i * V3_SLAVE_ENTRY_SIZE
                ent = slave_table[off:off + V3_SLAVE_ENTRY_SIZE]
                slave_id = ent[0]
                flags = ent[1]
                channel_start = struct.unpack("<H", ent[2:4])[0]
                channel_count = struct.unpack("<H", ent[4:6])[0]
                pixel_count = struct.unpack("<H", ent[6:8])[0]
                data_offset = struct.unpack("<I", ent[8:12])[0]
                data_length = struct.unpack("<I", ent[12:16])[0]

                valid_bounds = (data_offset + data_length) <= pixel_data_size  # [1]
                slaves.append(SlaveEntry(
                    slave_id=slave_id, flags=flags,
                    channel_start=channel_start, channel_count=channel_count,
                    pixel_count=pixel_count,
                    data_offset=data_offset, data_length=data_length,
                    valid_bounds=valid_bounds,
                ))
            return slaves
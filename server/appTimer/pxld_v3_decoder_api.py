# light_control/pxld_v3_decoder_api.py
# 用於 Django API：讀 PXLD v3 指定 frame + 指定 slave 的 RGBW raw bytes
# 解析流程與驗證清單依規範 [1]

from __future__ import annotations
import base64
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

V3_FILE_HEADER_SIZE = 64
V3_FRAME_HEADER_SIZE = 32
V3_SLAVE_ENTRY_SIZE = 24

@dataclass
class FileHeader:
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
    file_crc32: int
    checksum_type: int
    crc32_ok: bool

@dataclass
class SlaveMeta:
    slave_id: int
    flags: int
    channel_start: int
    channel_count: int
    pixel_count: int
    data_offset: int
    data_length: int

class PXLDv3DecoderAPI:
    """
    PXLD v3 解碼器（偏 API 用途）
    - 建立 frame_offsets
    - 讀取指定 frame 的 SlaveTable + PixelData
    - 切片取指定 slave 的 RGBW bytes
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.path = Path(filepath)

        self.fh: Optional[FileHeader] = None
        self.frame_offsets: List[int] = []

        self._parse_and_index()

    # ---------- 基礎解析 ----------
    def _read_file_header(self, f) -> FileHeader:
        header = f.read(V3_FILE_HEADER_SIZE)
        if len(header) != V3_FILE_HEADER_SIZE:
            raise ValueError("FileHeader 長度不足")

        magic = header[0:4].decode("ascii", errors="ignore")
        if magic != "PXLD":
            raise ValueError("Magic 不是 PXLD")

        major = header[4]
        minor = header[5]
        if major != 3:
            raise ValueError(f"版本不支援：{major}.{minor}（僅支援 3.x）")

        fps = header[6]
        total_slaves = struct.unpack("<H", header[7:9])[0]
        total_frames = struct.unpack("<I", header[9:13])[0]
        total_pixels = struct.unpack("<I", header[13:17])[0]
        frame_header_size = struct.unpack("<H", header[17:19])[0]
        slave_entry_size = struct.unpack("<H", header[19:21])[0]
        udp_port = struct.unpack("<H", header[21:23])[0]
        file_crc32 = struct.unpack("<I", header[23:27])[0]
        checksum_type = header[27]

        # 驗證清單：frame_header_size=32, slave_entry_size=24 [1]
        if frame_header_size != V3_FRAME_HEADER_SIZE:
            raise ValueError(f"frame_header_size={frame_header_size}，預期 32")
        if slave_entry_size != V3_SLAVE_ENTRY_SIZE:
            raise ValueError(f"slave_entry_size={slave_entry_size}，預期 24")

        crc32_ok = self._verify_crc32(file_crc32, checksum_type)

        return FileHeader(
            magic=magic,
            major=major,
            minor=minor,
            fps=fps,
            total_slaves=total_slaves,
            total_frames=total_frames,
            total_pixels=total_pixels,
            frame_header_size=frame_header_size,
            slave_entry_size=slave_entry_size,
            udp_port=udp_port,
            file_crc32=file_crc32,
            checksum_type=checksum_type,
            crc32_ok=crc32_ok,
        )

    def _verify_crc32(self, declared_crc32: int, checksum_type: int) -> bool:
        # checksum_type==0 => 未啟用 [1]
        if checksum_type == 0:
            return True

        # 這裡用 zlib.crc32 計算整檔（如你 CRC 規則不同可再按規範調整）
        data = self.path.read_bytes()
        calc = zlib.crc32(data) & 0xFFFFFFFF
        return calc == declared_crc32

    def _parse_and_index(self):
        """
        完整流程：Header -> CRC32 -> frame index [1]
        frame_offsets 建立依 FrameHeader 的 slave_table_size / pixel_data_size 計算 [1][2]
        """
        with open(self.filepath, "rb") as f:
            self.fh = self._read_file_header(f)

            # 建立 frame_offsets
            self.frame_offsets = []
            cur = V3_FILE_HEADER_SIZE

            for _ in range(self.fh.total_frames):
                self.frame_offsets.append(cur)

                f.seek(cur)
                frame_header = f.read(V3_FRAME_HEADER_SIZE)
                if len(frame_header) != V3_FRAME_HEADER_SIZE:
                    break

                slave_table_size = struct.unpack("<I", frame_header[8:12])[0]   # [1][2]
                pixel_data_size = struct.unpack("<I", frame_header[12:16])[0]  # [1][2]

                # 驗證清單：slave_table_size = total_slaves * 24 [1]
                expect = self.fh.total_slaves * V3_SLAVE_ENTRY_SIZE
                if slave_table_size != expect:
                    raise ValueError(f"slave_table_size={slave_table_size} != total_slaves*24({expect})")

                # 下一幀偏移 [1][2]
                cur += V3_FRAME_HEADER_SIZE + slave_table_size + pixel_data_size

    # ---------- Frame 讀取 ----------
    def _read_frame_tables(self, frame_id: int) -> Dict:
        """
        讀取指定 frame 的：
        - FrameHeader
        - SlaveTable（解析成 list）
        - PixelData（bytes）
        """
        if frame_id < 0 or frame_id >= len(self.frame_offsets):
            raise ValueError(f"Frame {frame_id} 超出範圍")

        assert self.fh is not None

        with open(self.filepath, "rb") as f:
            f.seek(self.frame_offsets[frame_id])

            frame_header = f.read(V3_FRAME_HEADER_SIZE)
            if len(frame_header) != V3_FRAME_HEADER_SIZE:
                raise ValueError("FrameHeader 長度不足")

            actual_frame_id = struct.unpack("<I", frame_header[0:4])[0]
            slave_table_size = struct.unpack("<I", frame_header[8:12])[0]   # [1][2]
            pixel_data_size = struct.unpack("<I", frame_header[12:16])[0]  # [1][2]

            slave_table = f.read(slave_table_size)
            if len(slave_table) != slave_table_size:
                raise ValueError("SlaveTable 長度不足")

            pixel_data = f.read(pixel_data_size)
            if len(pixel_data) != pixel_data_size:
                raise ValueError("PixelData 長度不足")

            slaves: List[SlaveMeta] = []
            for i in range(self.fh.total_slaves):
                off = i * V3_SLAVE_ENTRY_SIZE
                ent = slave_table[off:off + V3_SLAVE_ENTRY_SIZE]
                sid = ent[0]
                flags = ent[1]
                channel_start = struct.unpack("<H", ent[2:4])[0]
                channel_count = struct.unpack("<H", ent[4:6])[0]
                pixel_count = struct.unpack("<H", ent[6:8])[0]
                data_offset = struct.unpack("<I", ent[8:12])[0]
                data_length = struct.unpack("<I", ent[12:16])[0]

                # 驗證清單：offset+len <= pixel_data_size [1]
                if data_offset + data_length > pixel_data_size:
                    raise ValueError(
                        f"Slave {sid} data slice 越界: offset={data_offset} len={data_length} pixel_data_size={pixel_data_size}"
                    )

                slaves.append(SlaveMeta(
                    slave_id=sid,
                    flags=flags,
                    channel_start=channel_start,
                    channel_count=channel_count,
                    pixel_count=pixel_count,
                    data_offset=data_offset,
                    data_length=data_length,
                ))

            return {
                "frame_id": actual_frame_id,
                "slaves": slaves,
                "pixel_data": pixel_data,
                "pixel_data_size": pixel_data_size,
            }

    # ---------- API：取某 slave 的 RGBW raw ----------
    def get_slave_rgbw_bytes(self, frame_id: int, slave_id: int) -> bytes:
        """
        獲取單個 slave 的 RGBW 數據
        支援 slave_id=-1 時返回所有 slave 的合併數據
        """
        # 如果是總畫板模式，返回所有 slave 的合併數據
        if slave_id == -1:
            all_data = self.get_all_slaves_rgbw_bytes(frame_id)
            
            # 合併所有 slave 的數據（按照 slave_id 排序）
            sorted_slaves = sorted(all_data.items())
            combined_bytes = b''.join(data for sid, data in sorted_slaves)
            return combined_bytes
        
        # 原有的單個 slave 邏輯
        frame = self._read_frame_tables(frame_id)
        slave = None
        for s in frame["slaves"]:
            if s.slave_id == slave_id:
                slave = s
                break
        
        if slave is None:
            available_slaves = [s.slave_id for s in frame["slaves"]]
            raise ValueError(f"Frame {frame_id} 找不到 slave_id={slave_id}，可用的 slave_ids: {available_slaves}")
        
        pixel_data = frame["pixel_data"]
        start = slave.data_offset
        end = start + slave.data_length
        
        if end > len(pixel_data):
            raise ValueError(f"Slave {slave_id} 數據越界: offset={start}, length={slave.data_length}, total={len(pixel_data)}")
        
        raw = pixel_data[start:end]
        
        # 驗證數據長度
        expected_len = slave.pixel_count * 4
        if len(raw) != expected_len:
            print(f"[警告] Slave {slave_id} 數據長度不匹配: 預期={expected_len}, 實際={len(raw)}")
        
        return raw

    def get_slave_rgbw_b64(self, frame_id: int, slave_id: int) -> str:
        raw = self.get_slave_rgbw_bytes(frame_id, slave_id)
        return base64.b64encode(raw).decode("ascii")
    
    def get_all_slaves_rgbw_bytes(self, frame_id: int) -> dict:
        """
        獲取指定幀的所有 slave RGBW 數據
        用於總畫板模式 (slave_id=-1)
        返回: {slave_id: bytes, ...}
        """
        frame = self._read_frame_tables(frame_id)
        result = {}
        
        for slave_meta in frame["slaves"]:
            sid = slave_meta.slave_id
            pixel_data = frame["pixel_data"]
            start = slave_meta.data_offset
            end = start + slave_meta.data_length
            
            # 安全檢查：確保切片不會越界
            if end > len(pixel_data):
                print(f"[警告] Slave {sid} 數據越界: offset={start}, length={slave_meta.data_length}")
                continue
                
            raw = pixel_data[start:end]
            result[sid] = raw
            
            # 可選：驗證數據長度
            expected_len = slave_meta.pixel_count * 4  # RGBW = 4 bytes
            if len(raw) != expected_len:
                print(f"[警告] Slave {sid} 數據長度不匹配: 預期={expected_len}, 實際={len(raw)}")
        
        return result
    
    def get_all_slaves_rgbw_b64(self, frame_id: int) -> dict:
        """
        獲取所有 slave 的 RGBW 數據（Base64 編碼）
        用於總畫板模式
        返回: {slave_id: base64_string, ...}
        """
        all_rgbw = self.get_all_slaves_rgbw_bytes(frame_id)
        return {
            sid: base64.b64encode(data).decode('ascii')
            for sid, data in all_rgbw.items()
        }

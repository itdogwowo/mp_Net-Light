from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct
import zlib

from .mapping import MappingConfigData, SlaveConfig


_PXLD_FILE_HEADER = struct.Struct("<4sBBBHIIHHHIBI32s")
_PXLD_FRAME_HEADER = struct.Struct("<IHHII16s")
_PXLD_SLAVE_ENTRY = struct.Struct("<BBHHHII8s")


def _lround_positive(x: float) -> int:
    return int(math.floor(x + 0.5))


def _crc32_file(path: Path, start_offset: int) -> int:
    crc = 0
    with path.open("rb") as f:
        f.seek(start_offset)
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


class PxldWriter:
    def __init__(self, output_path: str | Path, config: MappingConfigData, precise_fps: float) -> None:
        self._path = Path(output_path)
        self._config = config
        self._precise_fps = precise_fps if precise_fps > 0.0 else config.settings.fps
        self._f = None
        self._frame_count = 0
        self._slave_by_id: dict[int, SlaveConfig] = {s.slave_id: s for s in config.slaves}

    def open(self) -> None:
        f = self._path.open("wb")
        try:
            self._write_header(f)
            self._f = f
        except Exception:
            f.close()
            raise

    def close(self) -> None:
        if self._f is None:
            return
        self._f.close()
        self._f = None
        self._update_frame_count()
        self._update_crc32()

    def _write_header(self, f) -> None:
        fps_int = _lround_positive(self._precise_fps)
        fps_milli = _lround_positive(self._precise_fps * 1000.0)
        reserved = b"\x00" * 32
        header = _PXLD_FILE_HEADER.pack(
            b"PXLD",
            3,
            0,
            fps_int & 0xFF,
            int(self._config.settings.total_slaves) & 0xFFFF,
            0,
            int(self._config.settings.total_pixels) & 0xFFFFFFFF,
            32,
            24,
            int(self._config.network.udp_port) & 0xFFFF,
            0,
            1,
            int(fps_milli) & 0xFFFFFFFF,
            reserved,
        )
        f.write(header)

    def write_frame(self, frame_id: int, slave_data: dict[int, bytes | bytearray]) -> None:
        if self._f is None:
            raise RuntimeError("PXLD file not open")

        ordered_ids = sorted(slave_data.keys())
        slave_table_size = len(ordered_ids) * _PXLD_SLAVE_ENTRY.size
        pixel_data_size = sum(len(slave_data[sid]) for sid in ordered_ids)

        frame_header = _PXLD_FRAME_HEADER.pack(
            int(frame_id) & 0xFFFFFFFF,
            0,
            0,
            int(slave_table_size) & 0xFFFFFFFF,
            int(pixel_data_size) & 0xFFFFFFFF,
            b"\x00" * 16,
        )
        self._f.write(frame_header)

        current_offset = 0
        for sid in ordered_ids:
            data = slave_data[sid]
            slave = self._slave_by_id.get(sid)
            if slave is None:
                channel_start = 0
                channel_count = 0
            else:
                channel_start = slave.channels.start & 0xFFFF
                channel_count = slave.channels.count & 0xFFFF

            entry = _PXLD_SLAVE_ENTRY.pack(
                int(sid) & 0xFF,
                0,
                int(channel_start) & 0xFFFF,
                int(channel_count) & 0xFFFF,
                (len(data) // 4) & 0xFFFF,
                int(current_offset) & 0xFFFFFFFF,
                int(len(data)) & 0xFFFFFFFF,
                b"\x00" * 8,
            )
            self._f.write(entry)
            current_offset += len(data)

        for sid in ordered_ids:
            self._f.write(slave_data[sid])

        self._frame_count += 1

    def _update_frame_count(self) -> None:
        with self._path.open("r+b") as f:
            f.seek(9)
            f.write(struct.pack("<I", int(self._frame_count) & 0xFFFFFFFF))

    def _update_crc32(self) -> None:
        crc = _crc32_file(self._path, 27)
        with self._path.open("r+b") as f:
            f.seek(23)
            f.write(struct.pack("<I", int(crc) & 0xFFFFFFFF))


@dataclass(frozen=True)
class PxldHeader:
    major_version: int
    minor_version: int
    fps: int
    total_slaves: int
    total_frames: int
    total_pixels: int
    frame_header_size: int
    slave_entry_size: int
    udp_port: int
    file_crc32: int
    checksum_type: int
    fps_milli: int

    @property
    def exact_fps(self) -> float:
        if self.fps_milli:
            return float(self.fps_milli) / 1000.0
        return float(self.fps)


class PxldReader:
    def __init__(self, input_path: str | Path) -> None:
        self._path = Path(input_path)
        self._f = None
        self._header: PxldHeader | None = None

    @property
    def header(self) -> PxldHeader:
        if self._header is None:
            raise RuntimeError("PXLD file not open")
        return self._header

    def open(self) -> None:
        f = self._path.open("rb")
        try:
            raw = f.read(_PXLD_FILE_HEADER.size)
            if len(raw) != _PXLD_FILE_HEADER.size:
                raise RuntimeError("Failed to read PXLD file header")
            unpacked = _PXLD_FILE_HEADER.unpack(raw)
            magic = unpacked[0]
            if magic != b"PXLD":
                raise RuntimeError("Invalid PXLD file: magic number mismatch")
            major = int(unpacked[1])
            minor = int(unpacked[2])
            if major != 3:
                raise RuntimeError(f"Unsupported PXLD version: {major}.{minor}")
            self._header = PxldHeader(
                major_version=major,
                minor_version=minor,
                fps=int(unpacked[3]),
                total_slaves=int(unpacked[4]),
                total_frames=int(unpacked[5]),
                total_pixels=int(unpacked[6]),
                frame_header_size=int(unpacked[7]),
                slave_entry_size=int(unpacked[8]),
                udp_port=int(unpacked[9]),
                file_crc32=int(unpacked[10]),
                checksum_type=int(unpacked[11]),
                fps_milli=int(unpacked[12]),
            )
            self._f = f
        except Exception:
            f.close()
            raise

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
        self._f = None
        self._header = None

    def iter_frames(self):
        if self._f is None:
            raise RuntimeError("PXLD file not open")
        h = self.header
        self._f.seek(_PXLD_FILE_HEADER.size)
        for _ in range(h.total_frames):
            frame_header_bytes = self._f.read(_PXLD_FRAME_HEADER.size)
            if len(frame_header_bytes) != _PXLD_FRAME_HEADER.size:
                raise RuntimeError("Failed to read frame header")
            frame_id, flags, reserved1, slave_table_size, pixel_data_size, _ = _PXLD_FRAME_HEADER.unpack(frame_header_bytes)
            slave_entries_bytes = self._f.read(slave_table_size)
            if len(slave_entries_bytes) != slave_table_size:
                raise RuntimeError(f"Failed to read slave table at frame {frame_id}")
            all_pixel_data = self._f.read(pixel_data_size)
            if len(all_pixel_data) != pixel_data_size:
                raise RuntimeError(f"Failed to read pixel data at frame {frame_id}")

            num_slaves = slave_table_size // _PXLD_SLAVE_ENTRY.size
            slave_data: dict[int, bytes] = {}
            for i in range(num_slaves):
                entry = _PXLD_SLAVE_ENTRY.unpack_from(slave_entries_bytes, i * _PXLD_SLAVE_ENTRY.size)
                slave_id = int(entry[0])
                data_offset = int(entry[5])
                data_length = int(entry[6])
                slave_data[slave_id] = all_pixel_data[data_offset : data_offset + data_length]

            yield int(frame_id), slave_data


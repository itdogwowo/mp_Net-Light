from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct


_FSEQ_HEADER_STRUCT = struct.Struct("<4sHBBHIIbbHBBQ")


def _lround_positive(x: float) -> int:
    return int(math.floor(x + 0.5))


@dataclass(frozen=True)
class FseqHeader:
    magic: bytes
    channel_data_offset: int
    minor_version: int
    major_version: int
    header_length: int
    channel_count: int
    frame_count: int
    step_time_ms: int
    flags: int
    compression_type: int
    compression_level: int
    num_sparse_ranges: int
    uuid: int


class FseqReader:
    def __init__(self, filepath: str | Path) -> None:
        self._path = Path(filepath)
        self._f = None
        self._header: FseqHeader | None = None
        self._frame_data_offset = 0

    @property
    def header(self) -> FseqHeader:
        if self._header is None:
            raise RuntimeError("FSEQ file not open")
        return self._header

    def open(self) -> None:
        f = self._path.open("rb")
        try:
            raw = f.read(_FSEQ_HEADER_STRUCT.size)
            if len(raw) != _FSEQ_HEADER_STRUCT.size:
                raise RuntimeError("Failed to read FSEQ header")
            unpacked = _FSEQ_HEADER_STRUCT.unpack(raw)
            header = FseqHeader(
                magic=unpacked[0],
                channel_data_offset=int(unpacked[1]),
                minor_version=int(unpacked[2]),
                major_version=int(unpacked[3]),
                header_length=int(unpacked[4]),
                channel_count=int(unpacked[5]),
                frame_count=int(unpacked[6]),
                step_time_ms=int(unpacked[7]) & 0xFF,
                flags=int(unpacked[8]) & 0xFF,
                compression_type=int(unpacked[9]),
                compression_level=int(unpacked[10]) & 0xFF,
                num_sparse_ranges=int(unpacked[11]) & 0xFF,
                uuid=int(unpacked[12]),
            )

            if header.magic != b"PSEQ":
                raise RuntimeError("Invalid FSEQ magic number")
            if header.major_version != 2:
                raise RuntimeError(f"Unsupported FSEQ version: {header.major_version}.{header.minor_version}")
            if header.compression_type != 0:
                raise RuntimeError(f"Compressed FSEQ not supported (compression type: {header.compression_type})")

            self._f = f
            self._header = header
            self._frame_data_offset = header.channel_data_offset
        except Exception:
            f.close()
            raise

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
        self._f = None
        self._header = None
        self._frame_data_offset = 0

    def get_exact_fps(self) -> float:
        h = self.header
        if h.step_time_ms == 0:
            return 40.0
        return 1000.0 / float(h.step_time_ms)

    def get_fps(self) -> int:
        h = self.header
        if h.step_time_ms == 0:
            return 40
        return _lround_positive(self.get_exact_fps())

    def iter_frames(self):
        if self._f is None:
            raise RuntimeError("FSEQ file not open")
        h = self.header
        self._f.seek(self._frame_data_offset)
        frame_size = h.channel_count
        for frame_id in range(h.frame_count):
            frame = self._f.read(frame_size)
            if len(frame) != frame_size:
                raise RuntimeError(f"Unexpected end of FSEQ while reading frame {frame_id}")
            yield frame_id, frame


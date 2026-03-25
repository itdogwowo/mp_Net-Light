from __future__ import annotations

from pathlib import Path
import json
import struct
import tempfile

from .cli_fseq_to_pxld import main as convert_main
from .pxld import PxldReader


_FSEQ_HEADER_STRUCT = struct.Struct("<4sHBBHIIbbHBBQ")


def _write_test_fseq(path: Path) -> None:
    channel_data_offset = _FSEQ_HEADER_STRUCT.size
    header = _FSEQ_HEADER_STRUCT.pack(
        b"PSEQ",
        channel_data_offset,
        2,
        2,
        28,
        4,
        3,
        25,
        0,
        0,
        0,
        0,
        0,
    )
    frames = [
        bytes([10, 20, 30, 40]),
        bytes([0, 0, 0, 0]),
        bytes([255, 255, 255, 1]),
    ]
    with path.open("wb") as f:
        f.write(header)
        for fr in frames:
            f.write(fr)


def _write_test_mapping(path: Path) -> None:
    mapping = {
        "network": {"udp_port": 4050},
        "settings": {"fps": 40.0, "total_channels": 4, "total_pixels": 2, "total_slaves": 1},
        "slaves": [
            {
                "slave_id": 0,
                "channels": {"start": 1, "count": 4},
                "outputs": [
                    {"type": "WS2812B", "label": "rgb", "count": 1, "channels_per_pixel": 3, "channel_start": 1},
                    {"type": "STANDARD_LED", "label": "pwm", "count": 1, "channels_per_pixel": 1, "channel_start": 4},
                ],
            }
        ],
    }
    path.write_text(json.dumps(mapping), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        fseq_path = td_path / "test.fseq"
        map_path = td_path / "mapping.json"
        pxld_path = td_path / "out.pxld"

        _write_test_fseq(fseq_path)
        _write_test_mapping(map_path)

        rc = convert_main([str(fseq_path), str(map_path), str(pxld_path), "--lenient"])
        if rc != 0:
            raise RuntimeError("Converter returned non-zero exit code")

        reader = PxldReader(pxld_path)
        reader.open()
        h = reader.header
        if h.total_frames != 3:
            raise RuntimeError(f"Unexpected total_frames: {h.total_frames}")
        if h.checksum_type != 1:
            raise RuntimeError("checksum_type expected 1")

        frames = list(reader.iter_frames())
        if len(frames) != 3:
            raise RuntimeError("Unexpected number of frames")

        f0 = frames[0][1][0]
        if f0 != bytes([10, 20, 30, 0xFF, 0, 0, 0, 40]):
            raise RuntimeError(f"Unexpected frame0 payload: {f0!r}")

        f1 = frames[1][1][0]
        if f1 != bytes([0, 0, 0, 0xFF, 0, 0, 0, 0]):
            raise RuntimeError(f"Unexpected frame1 payload: {f1!r}")

        f2 = frames[2][1][0]
        if f2 != bytes([255, 255, 255, 0xFF, 0, 0, 0, 1]):
            raise RuntimeError(f"Unexpected frame2 payload: {f2!r}")

        reader.close()

    print("Selftest OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


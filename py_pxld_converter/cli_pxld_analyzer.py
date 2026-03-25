from __future__ import annotations

import argparse

from .pxld import PxldReader


def _is_frame_all_zero(slave_data: dict[int, bytes]) -> bool:
    for data in slave_data.values():
        mv = memoryview(data)
        for i in range(0, len(mv), 4):
            r = mv[i + 0]
            g = mv[i + 1]
            b = mv[i + 2]
            w = mv[i + 3]
            if r != 0 or g != 0 or b != 0 or (w != 0 and w != 0xFF):
                return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pxld_analyzer_py",
        description="Analyzes PXLD v3 file to find consecutive frames with zero brightness.",
    )
    parser.add_argument("input_pxld")
    parser.add_argument("min_frames", nargs="?", type=int, default=10)
    args = parser.parse_args(argv)

    if args.min_frames <= 0:
        raise SystemExit("Error: MIN_FRAMES must be positive")

    print("=== PXLD Dark Frame Analyzer (Python) ===")
    print()

    reader = PxldReader(args.input_pxld)
    reader.open()
    h = reader.header
    print(f"PXLD v{h.major_version}.{h.minor_version} file opened")
    print(f"Frames: {h.total_frames}")
    print(f"FPS: {h.exact_fps}")
    print(f"Slaves: {h.total_slaves}")
    print(f"Total pixels: {h.total_pixels}")
    print()

    sequences: list[tuple[int, int, int]] = []
    in_dark = False
    seq_start = 0
    frame_count = h.total_frames
    progress_interval = max(1, frame_count // 20)

    print(f"Analyzing frames (min sequence length: {args.min_frames} frames)...")

    last_frame_id = 0
    for frame_id, slave_data in reader.iter_frames():
        last_frame_id = frame_id
        dark = _is_frame_all_zero(slave_data)
        if dark:
            if not in_dark:
                in_dark = True
                seq_start = frame_id
        else:
            if in_dark:
                seq_len = frame_id - seq_start
                if seq_len >= args.min_frames:
                    sequences.append((seq_start, frame_id - 1, seq_len))
                in_dark = False

        if frame_id % progress_interval == 0 or frame_id == frame_count - 1:
            progress = (frame_id + 1) * 100.0 / frame_count
            print(f"\rProgress: {progress:.1f}% ({frame_id + 1}/{frame_count})", end="", flush=True)

    if in_dark:
        seq_len = frame_count - seq_start
        if seq_len >= args.min_frames:
            sequences.append((seq_start, frame_count - 1, seq_len))

    print()
    print()
    print("=== Analysis Results ===")
    print()

    if not sequences:
        print(f"No dark sequences found (min length: {args.min_frames} frames)")
        reader.close()
        return 0

    print(f"Found {len(sequences)} dark sequence(s):")
    print()
    total_dark_frames = 0
    for i, (start, end, length) in enumerate(sequences, start=1):
        duration_s = float(length) / float(h.fps if h.fps else 1)
        if h.fps_milli:
            duration_s = float(length) / h.exact_fps
        total_dark_frames += length
        print(f"Sequence {i}:")
        print(f"  Frames: {start} - {end} ({length} frames)")
        print(f"  Duration: {duration_s:.2f} seconds")
        print()

    total_dark_duration = float(total_dark_frames) / h.exact_fps if h.exact_fps else 0.0
    print("Summary:")
    print(f"  Total dark frames: {total_dark_frames} / {frame_count} ({(total_dark_frames * 100.0 / frame_count):.1f}%)")
    print(f"  Total dark duration: {total_dark_duration:.2f} seconds")

    reader.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


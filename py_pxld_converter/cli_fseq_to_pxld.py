from __future__ import annotations

import argparse
import math
import time

from .channel_extractor import extract_slave_channels, convert_slave_data
from .fseq import FseqReader
from .mapping import load_mapping_config
from .pxld import PxldWriter


def _format_ms(frame_id: int, fps: float) -> int:
    return int(math.floor((float(frame_id) * 1000.0 / fps) + 0.5))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fseq_to_pxld_py",
        description="Converts xLights FSEQ V2 (uncompressed) to PXLD v3.",
    )
    parser.add_argument("input_fseq")
    parser.add_argument("mapping_config_json")
    parser.add_argument("output_pxld")
    parser.add_argument("--brightness", type=int, default=100)
    parser.add_argument("--cap-white", type=int, default=0, dest="cap_white")
    parser.add_argument("--lenient", action="store_true")
    args = parser.parse_args(argv)

    if args.brightness < 0 or args.brightness > 100:
        raise SystemExit("Error: brightness must be between 0 and 100")
    if args.cap_white < 0 or args.cap_white > 255:
        raise SystemExit("Error: white cap threshold must be between 0 and 255")

    strict_mode = not args.lenient
    brightness_percent = int(args.brightness)
    white_cap_threshold = int(args.cap_white)

    start_time = time.time()

    print("=== FSEQ to PXLD v3 Converter (Python) ===")
    print()
    print("Loading mapping configuration...")
    mapping = load_mapping_config(args.mapping_config_json)
    print(f"  Slaves: {len(mapping.slaves)}")
    print(f"  Total channels: {mapping.settings.total_channels}")
    print(f"  Total pixels: {mapping.settings.total_pixels}")
    print(f"  FPS (config): {mapping.settings.fps}")
    print()

    print("Opening FSEQ file...")
    fseq = FseqReader(args.input_fseq)
    fseq.open()
    exact_fps = fseq.get_exact_fps()
    print(f"  Version: {fseq.header.major_version}.{fseq.header.minor_version}")
    print(f"  Channels: {fseq.header.channel_count}")
    print(f"  Frames: {fseq.header.frame_count}")
    print(f"  FPS: {exact_fps}")
    print(f"  Duration: {fseq.header.frame_count / exact_fps} seconds")
    print()

    if fseq.header.channel_count < mapping.settings.total_channels:
        print(
            f"Warning: FSEQ has {fseq.header.channel_count} channels, but mapping requires {mapping.settings.total_channels}"
        )

    print("Creating PXLD file...")
    writer = PxldWriter(args.output_pxld, mapping, exact_fps)
    writer.open()
    print()

    print("Converting frames...")
    frame_count = fseq.header.frame_count
    progress_interval = max(1, frame_count // 20)

    channels_buffers: dict[int, bytearray] = {}
    pixel_buffers: dict[int, bytearray] = {}
    for slave in mapping.slaves:
        channels_buffers[slave.slave_id] = bytearray(slave.channels.count)
        pixel_buffers[slave.slave_id] = bytearray(slave.total_data_length)

    all_black = True
    first_nonzero_frame_id = -1

    for frame_id, frame_data in fseq.iter_frames():
        for slave in mapping.slaves:
            ch_buf = channels_buffers[slave.slave_id]
            px_buf = pixel_buffers[slave.slave_id]
            extract_slave_channels(frame_data, slave, ch_buf, strict_mode)
            convert_slave_data(ch_buf, slave, px_buf, brightness_percent, white_cap_threshold, strict_mode)

        writer.write_frame(frame_id, pixel_buffers)

        if all_black:
            found = False
            for pdata in pixel_buffers.values():
                mv = memoryview(pdata)
                for i in range(0, len(mv), 4):
                    if mv[i] != 0 or mv[i + 1] != 0 or mv[i + 2] != 0:
                        found = True
                        break
                if found:
                    break
            if found:
                all_black = False
                first_nonzero_frame_id = int(frame_id)

        if frame_id % progress_interval == 0 or frame_id == frame_count - 1:
            progress = (frame_id + 1) * 100.0 / frame_count
            print(f"\rProgress: {progress:.1f}% ({frame_id + 1}/{frame_count})", end="", flush=True)

    print()
    print()

    fseq.close()
    writer.close()

    end_time = time.time()
    duration_s = end_time - start_time

    print("=== Conversion Complete ===")
    print(f"Time taken: {duration_s:.2f} seconds")
    print(f"Frames processed: {frame_count}")
    if duration_s > 0:
        print(f"Average FPS: {frame_count / duration_s:.2f}")
    print(f"Brightness: {brightness_percent}%")
    print(f"White cap: {white_cap_threshold if white_cap_threshold > 0 else 'disabled'}")
    print(f"Mode: {'strict' if strict_mode else 'lenient'}")
    print()
    if all_black:
        print("Content: WARNING - output is entirely black (all pixels are zero)")
    else:
        first_ms = _format_ms(first_nonzero_frame_id, exact_fps)
        print("Content: has non-zero pixels")
        print(f"First non-zero pixel: frame {first_nonzero_frame_id} at {first_ms} ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


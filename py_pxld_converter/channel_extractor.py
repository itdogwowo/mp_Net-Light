from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .mapping import SlaveConfig


def _handle_issue(strict_mode: bool, message: str) -> None:
    if strict_mode:
        raise RuntimeError(message)
    print(f"[WARN] {message}")


def extract_slave_channels(frame_data: bytes, slave: SlaveConfig, out_channels: bytearray, strict_mode: bool) -> None:
    if len(out_channels) != slave.channels.count:
        out_channels[:] = b""
        out_channels.extend(b"\x00" * slave.channels.count)
    else:
        out_channels[:] = b"\x00" * len(out_channels)

    array_start = slave.channels.start - 1
    if array_start >= len(frame_data):
        _handle_issue(strict_mode, f"Slave {slave.slave_id} channel start exceeds frame data size")
        return

    available = min(slave.channels.count, len(frame_data) - array_start)
    out_channels[:available] = frame_data[array_start : array_start + available]
    if available < slave.channels.count:
        _handle_issue(
            strict_mode,
            f"Slave {slave.slave_id} channel data truncated (expected {slave.channels.count} bytes, got {available})",
        )


def convert_slave_data(
    channel_data: bytes | bytearray,
    slave: SlaveConfig,
    out_pixels: bytearray,
    brightness_percent: int,
    white_cap_threshold: int,
    strict_mode: bool,
) -> None:
    if len(out_pixels) != slave.total_data_length:
        out_pixels[:] = b""
        out_pixels.extend(b"\x00" * slave.total_data_length)
    else:
        out_pixels[:] = b"\x00" * len(out_pixels)

    for output in slave.outputs:
        if output.channel_start < slave.channels.start:
            _handle_issue(
                strict_mode,
                f"Output {output.label} on slave {slave.slave_id} has channel_start before slave start",
            )
            continue

        rel_start = (output.channel_start - 1) - (slave.channels.start - 1)
        required_channels = output.count * output.channels_per_pixel

        if rel_start + required_channels > len(channel_data):
            _handle_issue(
                strict_mode,
                f"Output {output.label} on slave {slave.slave_id} exceeds channel buffer",
            )
            continue

        if output.data_offset + output.data_length > len(out_pixels):
            _handle_issue(
                strict_mode,
                f"Output {output.label} on slave {slave.slave_id} exceeds pixel buffer",
            )
            continue

        dest = memoryview(out_pixels)[output.data_offset : output.data_offset + output.data_length]
        src = memoryview(channel_data)[rel_start : rel_start + required_channels]

        if output.type in ("APA102C", "WS2812B"):
            for i in range(output.count):
                base = i * output.channels_per_pixel
                r = int(src[base + 0])
                g = int(src[base + 1])
                b = int(src[base + 2])
                if white_cap_threshold > 0 and r >= white_cap_threshold and g >= white_cap_threshold and b >= white_cap_threshold:
                    r = white_cap_threshold
                    g = white_cap_threshold
                    b = white_cap_threshold
                dest[i * 4 + 0] = (r * brightness_percent) // 100
                dest[i * 4 + 1] = (g * brightness_percent) // 100
                dest[i * 4 + 2] = (b * brightness_percent) // 100
                dest[i * 4 + 3] = 0xFF
        elif output.type == "STANDARD_LED":
            for i in range(output.count):
                dest[i * 4 + 0] = 0
                dest[i * 4 + 1] = 0
                dest[i * 4 + 2] = 0
                dest[i * 4 + 3] = src[i]
        else:
            _handle_issue(strict_mode, f"Unknown output type '{output.type}' on slave {slave.slave_id}")


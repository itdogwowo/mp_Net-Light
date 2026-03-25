from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class NetworkConfig:
    broadcast: str
    udp_port: int
    protocol: str


@dataclass(frozen=True)
class ProjectSettings:
    fps: float
    total_channels: int
    total_pixels: int
    total_slaves: int


@dataclass
class OutputConfig:
    type: str
    label: str
    count: int
    channels_per_pixel: int
    bytes_per_pixel: int
    channel_start: int
    channel_end: int
    data_offset: int
    data_length: int


@dataclass
class SlaveChannels:
    start: int
    end: int
    count: int


@dataclass
class SlaveConfig:
    slave_id: int
    name: str
    ip: str
    channels: SlaveChannels
    outputs: list[OutputConfig]
    total_data_length: int


@dataclass(frozen=True)
class MappingConfigData:
    network: NetworkConfig
    settings: ProjectSettings
    slaves: list[SlaveConfig]


def load_mapping_config(path: str | Path) -> MappingConfigData:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))

    net = data.get("network") or {}
    network = NetworkConfig(
        broadcast=str(net.get("broadcast", "192.168.1.255")),
        udp_port=int(net.get("udp_port", 4050)),
        protocol=str(net.get("protocol", "RAW_UDP")),
    )

    settings_data = data.get("settings") or {}
    settings = ProjectSettings(
        fps=float(settings_data.get("fps", 40.0)),
        total_channels=int(settings_data.get("total_channels", 0)),
        total_pixels=int(settings_data.get("total_pixels", 0)),
        total_slaves=int(settings_data.get("total_slaves", 37)),
    )

    slaves: list[SlaveConfig] = []
    for slave_json in (data.get("slaves") or []):
        slave_id = int(slave_json.get("slave_id", 0))
        name = str(slave_json.get("name", ""))
        ip = str(slave_json.get("ip", ""))

        ch = slave_json.get("channels") or {}
        ch_start = int(ch.get("start", 0))
        ch_count = int(ch.get("count", 0))
        ch_end = int(ch.get("end", ch_start + ch_count - 1 if ch_count > 0 else 0))
        channels = SlaveChannels(start=ch_start, end=ch_end, count=ch_count)

        outputs: list[OutputConfig] = []
        for output_json in (slave_json.get("outputs") or []):
            out_type = str(output_json.get("type", ""))
            label = str(output_json.get("label", ""))
            count = int(output_json.get("count", 0))
            cpp = int(output_json.get("channels_per_pixel", 3))
            bpp = int(output_json.get("bytes_per_pixel", cpp))
            o_channel_start = int(output_json.get("channel_start", 0))
            o_channel_end = int(output_json.get("channel_end", o_channel_start + count * cpp - 1 if count > 0 else 0))

            outputs.append(
                OutputConfig(
                    type=out_type,
                    label=label,
                    count=count,
                    channels_per_pixel=cpp,
                    bytes_per_pixel=bpp,
                    channel_start=o_channel_start,
                    channel_end=o_channel_end,
                    data_offset=int(output_json.get("data_offset", 0)),
                    data_length=int(output_json.get("data_length", 0)),
                )
            )

        total_data_length = 0
        for out in outputs:
            out.data_offset = total_data_length
            out.data_length = out.count * 4
            total_data_length += out.data_length

        slaves.append(
            SlaveConfig(
                slave_id=slave_id,
                name=name,
                ip=ip,
                channels=channels,
                outputs=outputs,
                total_data_length=total_data_length,
            )
        )

    return MappingConfigData(network=network, settings=settings, slaves=slaves)


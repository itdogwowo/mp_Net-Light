<div align="center">

# mp_Net-Light

**MicroPython Networked LED Control System**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-ESP32|S3|P4-green.svg)]()
[![MicroPython](https://img.shields.io/badge/MicroPython-≥1.26-orange.svg)]()

*Not just another LED controller. A dual-core, protocol-driven, heterogeneous lighting platform.*

---

</div>

## Overview

**mp_Net-Light** is a high-performance networked LED control system built on **ESP32 / S3 / P4 + MicroPython**. It transforms a microcontroller into a full-fledged **network node** capable of driving **WS2812, APA102, and PCA9685 simultaneously** — controlled in real-time over TCP/WebSocket, synced with xLights sequences, and managed with industrial-grade file transfer and atomic writes.

Unlike WLED (general-purpose home lighting) or FPP (large-scale sequence player), mp_Net-Light occupies a unique intersection:

- **Pure Python development** — iterate in seconds, no C toolchain
- **True dual-core architecture** — network I/O on Core 0, LED rendering on Core 1, no contention
- **Heterogeneous LED mixing** — WS2812 + APA102 + PCA9685 on a single ESP32, driven from one unified buffer
- **Protocol-driven by design** — schema-defined commands, extensible without recompile
- **xLights sequence support** — PXLD v3 format bridges professional lighting design to MicroPython playback

---

## Supported Hardware

| SoC | Cores | Ethernet | WiFi | Status |
|-----|-------|----------|------|--------|
| **ESP32** (LX6) | 2× Xtensa | RMII + SPI (W5500) | 2.4 GHz | ✅ Primary target |
| **ESP32-S3** (LX7) | 2× Xtensa | SPI (W5500) | 2.4 GHz | ✅ Network tested |
| **ESP32-P4** (RISC-V) | 2× RISC-V | RMII | ❌ (no WiFi) | ✅ Verified with Ethernet (~1ms ping) |

All three support MicroPython ≥1.26 with full Viper native code emitter.

---

## Architecture

```
                    ┌──────────────────────────────────────────┐
                    │            ESP32 Dual-Core               │
                    │                                          │
Core 0 (Network)    │            Core 1 (Rendering)            │
                    │                                          │
┌──────────────────┐│  ┌─────────────────────────────────────┐ │
│  Network Task    ││  │  Render Task                        │ │
│  · TCP/WS/UDP    ││  │  · Consume from AtomicStreamHub     │ │
│  · Bus Decode    │◀──▶  · LEDController.show_all()          │ │
│  · Supply Chain  ││  │  · Maintain frame timing             │ │
│  · Web UI        ││  └─────────────────────────────────────┘ │
└────────┬─────────┘│                                          │
         │          │                                          │
         ▼          │                                          │
┌──────────────────┐│                                          │
│  AtomicStreamHub ││  Zero-copy, lock-free ring buffer        │
│  (3-slot state)  ││  IDLE → READY → READING                  │
└──────────────────┘│                                          │
                    └──────────────────────────────────────────┘
         │                          │
         │     SysBus (Services,    │
         │     Providers, Shared)   │
         │                          │
┌────────▼──────────────────────────▼──────────────────────────┐
│                    PC Control                                  │
│  · Django server (WebSocket + REST + Web UI)                 │
│  · NetBusMaster CLI (direct TCP control, no server needed)   │
│  · PXLD v3 decoder for xLights sequence playback             │
│  · Slave discovery via UDP heartbeat                         │
└──────────────────────────────────────────────────────────────┘
```

**Core 0** handles all I/O: TCP/WebSocket connections, binary protocol parsing, schema decoding, file system operations. **Core 1** is dedicated to LED rendering: consuming frame data from the lock-free `AtomicStreamHub`, performing Viper-accelerated pixel format conversion, and driving the physical LED hardware.

Communication between cores happens through `AtomicStreamHub` — a multi-slot ring buffer using atomic state transitions (`IDLE → READY → READING`), requiring no locks and producing zero garbage collection pressure.

---

## Features

### Core System

| Feature | Description |
|---------|-------------|
| **Dual-Core Architecture** | Network I/O on Core 0, LED rendering on Core 1 — no frame drops under load |
| **Schema-Driven Protocol** | Commands defined in JSON Schema; add new commands without recompiling firmware |
| **AtomicStreamHub** | Lock-free, zero-copy, 3-slot ring buffer for inter-core data transfer |
| **SysBus** | Service registry, dynamic providers, and shared state |
| **Task Orchestrator** | Register tasks with core affinity; migrate between cores at runtime |
| **CLI Tools** | `NetBusMaster.py` for direct TCP/WS device control without server dependency |
| **Performance Benchmarks** | Built-in RAM bandwidth test (discard/copy/hub_copy modes) for measuring protocol throughput |

### LED Drivers

| Driver | Type | Interface | Speed | Features |
|--------|------|-----------|-------|----------|
| **WS2812 / NeoPixel** | Single-wire | GPIO | RMT-class timing via MicroPython | Multi-strip, configurable color order |
| **APA102 / DotStar** | SPI | Hardware SPI (8 MHz) | Viper-accelerated frame conversion | Dual-buffer, gamma-like brightness header |
| **PCA9685** | I2C PWM | I2C (400 kHz) | 16-channel, 12-bit resolution | Viper-accelerated register packing |

**Unique capability**: All three driver types can operate **simultaneously** from a single unified RGBW frame buffer. A single `LEDStreamer.show_all()` call converts and outputs to WS2812 strips, APA102 strips, and PCA9685 PWM channels in one pass.

### Network

| Interface | Type | Details |
|-----------|------|---------|
| **WiFi STA** | Wireless | Auto-connect with config fallback to AP mode |
| **WiFi AP** | Wireless | Failsafe hotspot for headless configuration |
| **RMII Ethernet** | Wired | LAN8720 / IP101 PHY support (ESP32, ESP32-P4) |
| **SPI Ethernet** | Wired | WIZNET5K (W5500) support (ESP32, ESP32-S3) |

| Protocol | Transport | Purpose |
|----------|-----------|---------|
| **NetBus Binary** | TCP / WebSocket | Primary control channel with CRC32 validation |
| **UDP Discovery** | UDP Broadcast | Device heartbeat and auto-discovery |
| **HTTP** | TCP | Embedded Web UI on port 80 |
| **mDNS** | UDP | Local network name resolution |

### Control Options

You don't need the Django server to control devices. Two options:

- **Django Server** (`server/`): Full WebSocket-based control, REST API, Web UI, PXLD playback management, device discovery dashboard
- **NetBusMaster CLI** (`tools/NetBusMaster.py`): Direct TCP/WebSocket control — send commands, manage files, run benchmarks, control playback. Zero server setup required.

### Sequence Playback

```
xLights (lighting design)
    ↓ Render RGB data
[Converter] → PXLD v3 file (.pxld)
    ↓ PXLDv3Splitter
Per-slave .bin files (raw RGBW frames)
    ↓ TCP file transfer (atomic write + SHA256 verify)
ESP32 local flash storage
    ↓ PLAY command with future-time sync
Dual-core playback from local flash
    ↓ LED output (WS2812 / APA102 / PCA9685)
```

- **xLights integration**: Convert xLights-rendered sequences to PXLD v3, then split per slave
- **Local playback**: Full sequences stored on ESP32 flash/SD card — zero network dependency during playback
- **Frame-accurate sync**: Future-time PLAY command enables sub-millisecond multi-device synchronization
- **Seek, pause, loop**: Full transport control via protocol commands

### File Transfer

- **Chunk-based upload** with resume support
- **Atomic writes**: File is finalized only after SHA256 verification
- **File manifest caching**: Accelerates directory queries
- **Full filesystem scan**: On-demand with manifest generation

### System Management

- **OTA file updates**: Push new Python modules over the network — no firmware reflash needed
- **WiFi scanning**: List nearby access points on demand
- **Configuration persistence**: JSON + BTree database; passwords auto-isolated to secure storage
- **Embedded Web UI**: Control panel served from the device itself, accessible from any browser
- **WebSocket monitor**: Real-time FPS, frame count, and device metrics

---

## Performance

| Metric | Value | Conditions |
|--------|-------|------------|
| **Raw TCP throughput** | 2~3 MB/s | ESP32 WiFi, no protocol processing |
| **Effective throughput (full stack)** | 400~500 KB/s | CRC32 + Schema decode + Dispatch + Hub transfer |
| **CRC32 decode speed** | 4~5 MB/s | MicroPython with Viper optimization |
| **LED rendering** | 40+ FPS @ 1000+ LEDs | Dual-core with `@micropython.viper` conversion |
| **Ethernet ping** | ~1ms | RMII PHY on LAN / ESP32-P4, no WiFi jitter |
| **S3 network test** | ✅ Verified | ESP32-S3 with W5500 Ethernet tested |

**Scaling**: At 40 FPS, 500 KB/s supports ~3200 RGBW LEDs. For larger installations, sequences are pre-loaded to local flash, making playback performance independent of network throughput.

**Future headroom (same hardware, same MicroPython)**:

| Optimization | Expected gain | Method |
|:------------|:-------------:|--------|
| Dispatch array lookup | 3~5x | Pre-allocated array instead of dict |
| Schema decode cache | 3~4x | Pre-compiled layouts + `dict.clear()` reuse |
| Viper byte marshalling | 5~10x | `ptr8`/`ptr32` direct memory access |

Target: **2~3 MB/s effective throughput** (see [`doc/PROTOCOL_OPTIMIZATION_PLAN.md`](doc/PROTOCOL_OPTIMIZATION_PLAN.md))

---

## Project Structure

```
mp_Net-Light/
├── slave/                          # ESP32 MicroPython firmware
│   ├── boot.py                     # Hardware init (SPI, I2C, LED, SD)
│   ├── main.py                     # Entry: TaskManager + dual-core launch
│   ├── app.py                      # App: SchemaStore + Dispatcher assembly
│   ├── config.json                 # Device configuration (LEDs, network, buses)
│   ├── lib/                        # Core libraries
│   │   ├── sys_bus.py              # Service registry + shared state
│   │   ├── proto.py                # Binary packet (SOF/CRC/encode/decode)
│   │   ├── dispatch.py             # Command dispatcher
│   │   ├── schema_codec.py         # Schema-driven payload codec
│   │   ├── net_bus.py              # Network transport abstraction
│   │   ├── network_manager.py      # WiFi/Ethernet interface manager
│   │   ├── task.py                 # Task base class
│   │   ├── task_manager.py         # Dual-core task orchestrator
│   │   ├── buffer_hub.py           # AtomicStreamHub (lock-free ring buffer)
│   │   ├── fs_manager.py           # File system + SHA256 verification
│   │   ├── LEDController.py        # Unified LED driver controller
│   │   ├── apa102.py               # APA102 SPI driver (Viper accelerated)
│   │   ├── pca9685.py              # PCA9685 I2C PWM driver
│   │   └── ConfigManager.py        # JSON + BTree config persistence
│   ├── action/                     # Command handlers
│   │   ├── registry.py             # Command registration hub
│   │   ├── stream_actions.py       # LED stream play/pause/seek
│   │   ├── file_actions.py         # File transfer BEGIN/CHUNK/END
│   │   ├── sys_actions.py          # System discovery/connect
│   │   ├── status_actions.py       # Status query/report
│   │   ├── heartbeat_actions.py    # UDP heartbeat broadcast
│   │   └── ram_bench_actions.py    # RAM bandwidth benchmark
│   ├── tasks/                      # Background tasks (affinity-assigned)
│   │   ├── network.py              # Core 0: Network I/O
│   │   ├── bus_decode.py           # Core 0: Protocol decode
│   │   ├── render.py               # Core 1: LED rendering
│   │   └── web_ui.py               # Core 0: Embedded web server
│   └── schema/                     # Protocol schema definitions
│       ├── sys.json                # System commands
│       ├── status.json             # Status commands
│       ├── heartbeat.json          # Heartbeat commands
│       ├── file.json               # File transfer commands
│       ├── stream.json             # Stream playback commands
│       └── ram_bench.json          # RAM benchmark commands
├── server/                         # PC-side Django server (optional)
│   ├── core/                       # Discovery + protocol services
│   └── light_control/              # WebSocket playback + REST API
├── tools/                          # PC tools (CLI, no server needed)
│   ├── NetBusMaster.py             # Full device management console
│   ├── PXLDv3Splitter.py           # xLights sequence → per-slave .bin
│   └── pc_test_tool.py             # PC-side test and benchmark
├── doc/                            # Design documentation
│   ├── AI_CONTEXT.md               # Complete system reference
│   ├── DualCoreTaskOrchestrator.md  # Dual-core task design
│   ├── PROTOCOL_OPTIMIZATION_PLAN.md # Protocol throughput optimization
│   ├── RAM_BENCH.md                 # RAM benchmark protocol
│   └── performance_report.md        # Current performance baseline
└── function test/                   # Unit and integration benchmarks
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [`doc/AI_CONTEXT.md`](doc/AI_CONTEXT.md) | Complete system reference: architecture, protocol, schema, dual-core design |
| [`doc/DualCoreTaskOrchestrator.md`](doc/DualCoreTaskOrchestrator.md) | Task lifecycle, affinity, AtomicStreamHub design |
| [`doc/PROTOCOL_OPTIMIZATION_PLAN.md`](doc/PROTOCOL_OPTIMIZATION_PLAN.md) | Protocol throughput optimization: Viper, dispatch array, schema cache |
| [`doc/performance_report.md`](doc/performance_report.md) | Network performance baseline and tuning results |
| [`doc/RAM_BENCH.md`](doc/RAM_BENCH.md) | RAM bandwidth benchmark protocol details |

---

## Comparison

| Dimension | mp_Net-Light | WLED | FPP (Falcon Player) |
|-----------|:------------:|:----:|:-------------------:|
| **Language** | MicroPython | C++ (Arduino) | C++ / Python |
| **Hardware** | ESP32 / S3 / P4 | ESP8266 / ESP32 | Raspberry Pi / BeagleBone |
| **Dual-Core Architecture** | ✅ Explicit task separation | ❌ | ❌ (Linux process-based) |
| **Heterogeneous LED mixing** | ✅ WS2812+APA102+PCA9685 | ❌ Same type per instance | ✅ Via hardware channels |
| **Built-in effects** | ❌ (playback-focused) | ✅ 117+ effects | ✅ Via xLights sequences |
| **xLights integration** | ✅ PXLD v3 converter | ⚠️ Partial (UDP realtime) | ✅ Native |
| **Ethernet** | ✅ RMII + SPI (W5500) | ❌ WiFi only | ✅ (primary interface) |
| **Protocol** | Schema-driven binary (TCP/WS) | JSON API + E1.31/Art-Net | E1.31 / DDP / DMX |
| **File transfer** | Atomic write + SHA256 verify | Basic config backup | Linux filesystem |
| **OTA** | Python file push (no reflash) | Full firmware reflash | Package manager |
| **Control** | Django server **or** standalone CLI | Web UI + mobile apps | FPP web UI |
| **Dev cycle** | Edit → upload → run (~10s) | Edit → compile → flash (~2min) | Edit → build → deploy |
| **Target user** | Developers, artists, custom installations | General home users | Professional light shows |

### What this project is not

- **Not a WLED replacement** — WLED excels at out-of-box home lighting with 117+ effects and a polished UI. Use WLED when you need "smart lights in 30 minutes."
- **Not an FPP alternative** — FPP drives hundreds of thousands of LEDs via dedicated hardware controllers. It is the standard for professional Christmas and stage lighting.
- **A different tool for a different job** — mp_Net-Light is for **developers and makers** who need custom protocol logic, heterogeneous LED hardware, Python-level control over dual-core scheduling, and the ability to modify every layer of the stack.

---

## Quick Start

### Hardware Requirements

- ESP32 / ESP32-S3 / ESP32-P4 board (PSRAM recommended)
- USB cable for initial MicroPython flashing
- LED strip(s): WS2812, APA102, or PCA9685-based PWM LEDs
- (Optional) RMII Ethernet PHY (LAN8720/IP101) or SPI Ethernet (W5500)
- (Optional) MicroSD card module for large sequence storage

### Software Setup

1. **Flash MicroPython ≥1.26** to your board
2. **Upload the `slave/` directory** to the device filesystem
3. **Configure** `slave/config.json` for your LED setup and network
4. Choose your control method:
   - **CLI**: `python tools/NetBusMaster.py` (no server needed, direct control)
   - **Server**: `cd server && pip install -r requirements.txt && python manage.py runserver`
5. **Power on** — the device auto-connects via WebSocket

---

## License

[MIT](LICENSE)

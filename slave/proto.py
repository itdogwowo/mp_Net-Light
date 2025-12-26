# proto.py (VER=3)
# Packet format:
# SOF(2) VER(1) ADDR(2) CMD(2) LEN(2) DATA(LEN) CRC16(2)
#
# Strategy:
# - Always read full frame (HDR+DATA+CRC)
# - Verify CRC16
# - Then check ADDR (is mine or broadcast) and dispatch

import struct

SOF = b"NL"
CUR_VER = 3

# Address convention
ADDR_BROADCAST = 0xFFFF

# Header: SOF(2) VER(1) ADDR(2) CMD(2) LEN(2) => 9 bytes
HDR_FMT = "<2sBHHH"
HDR_LEN = struct.calcsize(HDR_FMT)  # 2+1+2+2+2 = 9

CRC_FMT = "<H"
CRC_LEN = 2

MAX_LEN_DEFAULT = 4096


def crc16_ccitt(data: bytes, init=0xFFFF) -> int:
    """CRC16-CCITT-FALSE (poly=0x1021, init=0xFFFF)"""
    crc = init
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def pack_packet(cmd: int, payload: bytes = b"", addr: int = ADDR_BROADCAST, ver: int = CUR_VER) -> bytes:
    """
    Build packet bytes:
      SOF + VER + ADDR + CMD + LEN + DATA + CRC16
    CRC covers: VER..LEN + DATA (SOF excluded)
    """
    if payload is None:
        payload = b""
    ln = len(payload)
    header = struct.pack(HDR_FMT, SOF, ver & 0xFF, addr & 0xFFFF, cmd & 0xFFFF, ln & 0xFFFF)

    crc_input = header[2:] + payload  # exclude SOF
    crc = crc16_ccitt(crc_input)

    return header + payload + struct.pack(CRC_FMT, crc)


def parse_one(packet: bytes, max_len=MAX_LEN_DEFAULT):
    """
    Parse exactly one packet (UDP/file use-case).
    Return (ver, addr, cmd, payload) or None.
    """
    if not packet or len(packet) < (HDR_LEN + CRC_LEN):
        return None

    sof, ver, addr, cmd, ln = struct.unpack_from(HDR_FMT, packet, 0)
    if sof != SOF:
        return None
    if ver != CUR_VER:
        return None
    if ln > max_len:
        return None

    need = HDR_LEN + ln + CRC_LEN
    if len(packet) != need:
        return None

    payload = packet[HDR_LEN:HDR_LEN + ln]
    crc_recv = struct.unpack_from(CRC_FMT, packet, HDR_LEN + ln)[0]
    crc_calc = crc16_ccitt(packet[2:HDR_LEN] + payload)

    if crc_recv != crc_calc:
        return None

    return ver, addr, cmd, payload


class StreamParser:
    """
    Stream parser for TCP/serial:
    - Handles packet fragmentation/coalescing
    - Resync by SOF
    - MicroPython-safe (no del bytearray slicing)
    """
    def __init__(self, max_len=MAX_LEN_DEFAULT, accept_addr=None):
        """
        accept_addr:
          - None: yield all valid packets
          - int: only yield addr==accept_addr or addr==broadcast
        """
        self.max_len = max_len
        self.accept_addr = accept_addr
        self.buf = bytearray()
        self.drop_bytes = 0

    def feed(self, data: bytes):
        if data:
            self.buf.extend(data)

    def _shrink_front(self, n: int):
        """Remove first n bytes (MicroPython compatible)"""
        if n <= 0:
            return
        if n >= len(self.buf):
            self.buf = bytearray()
        else:
            self.buf = self.buf[n:]

    def _shrink_keep_last(self, n_last: int):
        """Keep only last n_last bytes, drop the rest"""
        if n_last <= 0:
            self.drop_bytes += len(self.buf)
            self.buf = bytearray()
            return
        if len(self.buf) > n_last:
            self.drop_bytes += (len(self.buf) - n_last)
            self.buf = self.buf[-n_last:]

    def _resync_to_sof(self) -> bool:
        if len(self.buf) < 2:
            return False

        idx = self.buf.find(SOF)
        if idx < 0:
            # keep last 1 byte in case SOF splits
            self._shrink_keep_last(1)
            return False

        if idx > 0:
            self.drop_bytes += idx
            self._shrink_front(idx)

        return len(self.buf) >= HDR_LEN

    def _addr_ok(self, addr: int) -> bool:
        if self.accept_addr is None:
            return True
        return (addr == self.accept_addr) or (addr == ADDR_BROADCAST)

    def pop(self):
        """
        Yield (ver, addr, cmd, payload) for valid packets.
        Strategy1: always read full frame -> crc -> addr filter -> yield
        """
        while True:
            if not self._resync_to_sof():
                return

            if len(self.buf) < HDR_LEN:
                return

            sof, ver, addr, cmd, ln = struct.unpack_from(HDR_FMT, self.buf, 0)

            if sof != SOF:
                self.drop_bytes += 1
                self._shrink_front(1)
                continue

            if ver != CUR_VER:
                self.drop_bytes += 1
                self._shrink_front(1)
                continue

            if ln > self.max_len:
                self.drop_bytes += 1
                self._shrink_front(1)
                continue

            frame_len = HDR_LEN + ln + CRC_LEN
            if len(self.buf) < frame_len:
                return  # wait more

            payload = bytes(self.buf[HDR_LEN:HDR_LEN + ln])
            crc_recv = struct.unpack_from(CRC_FMT, self.buf, HDR_LEN + ln)[0]
            crc_calc = crc16_ccitt(bytes(self.buf[2:HDR_LEN]) + payload)

            if crc_recv != crc_calc:
                self.drop_bytes += 1
                self._shrink_front(1)
                continue

            # consume full frame
            self._shrink_front(frame_len)

            # after CRC ok, apply addr filter
            if not self._addr_ok(addr):
                continue

            yield ver, addr, cmd, payload
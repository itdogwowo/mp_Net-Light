# proto.py (VER=2)
# Packet format:
# SOF(2) VER(1) SRC(2) DST(2) CMD(2) LEN(2) DATA(LEN) CRC16(2)

import struct

SOF = b"NL"
CUR_VER = 2

# Header fields:
# SOF: 2s
# VER: u8
# SRC: u16
# DST: u16
# CMD: u16
# LEN: u16
HDR_FMT = "<2sBHHHH"
HDR_LEN = struct.calcsize(HDR_FMT)  # 2+1+2+2+2+2 = 11

CRC_FMT = "<H"
CRC_LEN = 2

MAX_LEN_DEFAULT = 4096

ADDR_BROADCAST = 0xFFFF


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


def pack_packet(cmd: int, payload: bytes = b"", src: int = 1, dst: int = ADDR_BROADCAST, ver: int = CUR_VER) -> bytes:
    """
    組包（任何通道通用）
    - cmd: u16
    - src/dst: u16
    - payload: bytes
    """
    if payload is None:
        payload = b""
    ln = len(payload)
    header = struct.pack(HDR_FMT, SOF, ver & 0xFF, src & 0xFFFF, dst & 0xFFFF, cmd & 0xFFFF, ln & 0xFFFF)

    # CRC 覆蓋：VER..LEN + DATA（不含 SOF）
    crc_input = header[2:] + payload
    crc = crc16_ccitt(crc_input)
    return header + payload + struct.pack(CRC_FMT, crc)


def parse_one(packet: bytes, max_len=MAX_LEN_DEFAULT):
    """
    單包解析（UDP/檔案）：成功回 (ver, src, dst, cmd, payload) 否則 None
    """
    if not packet or len(packet) < (HDR_LEN + CRC_LEN):
        return None

    sof, ver, src, dst, cmd, ln = struct.unpack_from(HDR_FMT, packet, 0)
    if sof != SOF:
        return None
    if ver != CUR_VER:
        # 如需兼容多版本，可在這裡擴展
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

    return ver, src, dst, cmd, payload


class StreamParser:
    """
    TCP/串口流式解析器：可處理黏包/拆包/雜訊
    MicroPython 兼容版：避免使用 del buf[:n] 這類切片刪除
    """
    def __init__(self, max_len=MAX_LEN_DEFAULT, accept_dst=None):
        self.max_len = max_len
        self.accept_dst = accept_dst
        self.buf = bytearray()
        self.drop_bytes = 0

    def feed(self, data: bytes):
        if data:
            self.buf.extend(data)

    def _shrink_front(self, n: int):
        """
        刪掉 buffer 前 n bytes（MicroPython 安全作法）
        注意：這會分配新的 bytearray，但最可靠且易懂
        """
        if n <= 0:
            return
        if n >= len(self.buf):
            self.buf = bytearray()
        else:
            self.buf = self.buf[n:]  # 重新切片生成新 bytearray

    def _shrink_keep_last(self, n_last: int):
        """
        只保留最後 n_last bytes，其餘丟棄
        """
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
            # 沒找到 SOF：保留最後 1 byte（避免 SOF 被拆成兩段）
            self._shrink_keep_last(1)
            return False

        if idx > 0:
            self.drop_bytes += idx
            self._shrink_front(idx)

        return len(self.buf) >= HDR_LEN

    def _dst_ok(self, dst: int) -> bool:
        if self.accept_dst is None:
            return True
        return (dst == self.accept_dst) or (dst == ADDR_BROADCAST)

    def pop(self):
        while True:
            if not self._resync_to_sof():
                return

            if len(self.buf) < HDR_LEN:
                return

            sof, ver, src, dst, cmd, ln = struct.unpack_from(HDR_FMT, self.buf, 0)

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
                return

            payload = bytes(self.buf[HDR_LEN:HDR_LEN + ln])
            crc_recv = struct.unpack_from(CRC_FMT, self.buf, HDR_LEN + ln)[0]
            crc_calc = crc16_ccitt(bytes(self.buf[2:HDR_LEN]) + payload)

            if crc_recv != crc_calc:
                self.drop_bytes += 1
                self._shrink_front(1)
                continue

            # consume 整包
            self._shrink_front(frame_len)

            if not self._dst_ok(dst):
                continue

            yield ver, src, dst, cmd, payload
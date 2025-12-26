# file_transfer.py
# 檔案傳輸接收端狀態機（三件套）
#
# 重要規則（你的決策）：
# - 所有 CMD 的 DATA 均以 dst_addr(u16 little-endian) 開頭
# - 先完整收幀+CRC ok，再進一步解析 data.dst_addr 與後續欄位
#
# 不回 ACK/ERR：你會透過最後查詢狀態或看 FILE_END 結果即可

import binascii

ADDR_BROADCAST = 0xFFFF

CMD_FILE_BEGIN = 0x2001
CMD_FILE_CHUNK = 0x2002
CMD_FILE_END   = 0x2003

# ---------------------------
# little-endian utils
# ---------------------------
def u16_le(b): return b[0] | (b[1] << 8)
def u32_le(b): return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

def p16_le(x): return bytes((x & 0xFF, (x >> 8) & 0xFF))
def p32_le(x): return bytes((x & 0xFF, (x >> 8) & 0xFF, (x >> 16) & 0xFF, (x >> 24) & 0xFF))


def sha256_digest_stream_from_file(path: str, bufsize=2048) -> bytes:
    """串流計算檔案 sha256 digest (32 bytes)"""
    import hashlib
    h = hashlib.sha256()
    buf = bytearray(bufsize)
    with open(path, "rb") as f:
        while True:
            try:
                n = f.readinto(buf)
                if not n:
                    break
                h.update(buf[:n])
            except AttributeError:
                data = f.read(bufsize)
                if not data:
                    break
                h.update(data)
    return h.digest()


def sha256_hex_from_digest(digest32: bytes) -> str:
    """把 32 bytes digest 轉 hex 字串（MicroPython 相容）"""
    return binascii.hexlify(digest32).decode()


class FileRxSession:
    """
    檔案接收 session（一次只處理一個 file_id，保持簡單且適合單核心）
    """
    def __init__(self, my_addr: int):
        self.my_addr = my_addr & 0xFFFF
        self.reset()

    def reset(self):
        self.active = False
        self.file_id = 0
        self.total_size = 0
        self.chunk_size = 0
        self.expect_sha256 = None  # 32 bytes digest
        self.path = None
        self.fp = None
        self.written = 0
        self.last_error = None
        self.last_result = None

    def _close_fp(self):
        if self.fp:
            try:
                self.fp.close()
            except Exception:
                pass
        self.fp = None

    def _dst_ok(self, dst_addr: int) -> bool:
        return (dst_addr == self.my_addr) or (dst_addr == ADDR_BROADCAST)

    def _preallocate_fast_or_fallback(self, path: str, total: int):
        """
        優先用快速方式擴展檔案大小：
          seek(total-1) + write(0)
        失敗再 fallback：寫滿 0（保守、慢但兼容）
        """
        try:
            with open(path, "wb") as f:
                if total > 0:
                    f.seek(total - 1)
                    f.write(b"\x00")
            return
        except Exception:
            pass

        zero = b"\x00" * 512
        with open(path, "wb") as f:
            left = total
            while left > 0:
                n = 512 if left >= 512 else left
                f.write(zero[:n])
                left -= n

    # ---------------------------
    # Public: build payloads (for offline tester or for server tooling)
    # ---------------------------
    @staticmethod
    def build_begin_payload(dst_addr: int, file_id: int, total_size: int, chunk_size: int, sha256_digest32: bytes, path: str) -> bytes:
        path_b = path.encode("utf-8")
        return b"".join([
            p16_le(dst_addr),
            p32_le(file_id),
            p32_le(total_size),
            p16_le(chunk_size),
            sha256_digest32,
            p16_le(len(path_b)),
            path_b
        ])

    @staticmethod
    def build_chunk_payload(dst_addr: int, file_id: int, offset: int, data: bytes) -> bytes:
        return p16_le(dst_addr) + p32_le(file_id) + p32_le(offset) + data

    @staticmethod
    def build_end_payload(dst_addr: int, file_id: int) -> bytes:
        return p16_le(dst_addr) + p32_le(file_id)

    # ---------------------------
    # Handlers
    # ---------------------------
    def on_begin(self, payload: bytes):
        """
        payload:
          dst(u16) file_id(u32) total(u32) chunk(u16) sha256(32) path_len(u16) path
        """
        self.last_error = None
        self.last_result = None

        if len(payload) < (2 + 4 + 4 + 2 + 32 + 2):
            self.last_error = "BEGIN_TOO_SHORT"
            return False

        dst = u16_le(payload[0:2])
        if not self._dst_ok(dst):
            # not for me: ignore
            return False

        p = 2
        file_id = u32_le(payload[p:p+4]); p += 4
        total   = u32_le(payload[p:p+4]); p += 4
        chunk   = u16_le(payload[p:p+2]); p += 2
        sha     = payload[p:p+32]; p += 32
        path_len = u16_le(payload[p:p+2]); p += 2

        if len(payload) < p + path_len:
            self.last_error = "BAD_PATH_LEN"
            return False

        path = payload[p:p+path_len].decode("utf-8")

        # reset old session
        self._close_fp()
        self.reset()

        # init session
        self.active = True
        self.file_id = file_id
        self.total_size = total
        self.chunk_size = chunk
        self.expect_sha256 = sha
        self.path = path

        # prepare file
        try:
            self._preallocate_fast_or_fallback(path, total)
            self.fp = open(path, "r+b")
        except Exception as e:
            self.last_error = "OPEN_FAIL:%s" % e
            self.active = False
            self._close_fp()
            return False

        return True

    def on_chunk(self, payload: bytes):
        """
        payload:
          dst(u16) file_id(u32) offset(u32) data(...)
        """
        if len(payload) < (2 + 4 + 4):
            self.last_error = "CHUNK_TOO_SHORT"
            return False

        dst = u16_le(payload[0:2])
        if not self._dst_ok(dst):
            return False

        if not self.active or self.fp is None:
            self.last_error = "NO_ACTIVE_SESSION"
            return False

        p = 2
        file_id = u32_le(payload[p:p+4]); p += 4
        offset  = u32_le(payload[p:p+4]); p += 4
        data    = payload[p:]

        if file_id != self.file_id:
            self.last_error = "FILE_ID_MISMATCH"
            return False

        end = offset + len(data)
        if end > self.total_size:
            self.last_error = "OUT_OF_RANGE"
            return False

        try:
            self.fp.seek(offset)
            self.fp.write(data)
            self.written += len(data)
        except Exception as e:
            self.last_error = "WRITE_FAIL:%s" % e
            return False

        return True

    def on_end(self, payload: bytes):
        """
        payload:
          dst(u16) file_id(u32)
        """
        if len(payload) < (2 + 4):
            self.last_error = "END_TOO_SHORT"
            return False

        dst = u16_le(payload[0:2])
        if not self._dst_ok(dst):
            return False

        if not self.active:
            self.last_error = "NO_ACTIVE_SESSION"
            return False

        file_id = u32_le(payload[2:6])
        if file_id != self.file_id:
            self.last_error = "FILE_ID_MISMATCH"
            return False

        # close before verify (flush)
        self._close_fp()

        # verify sha256
        try:
            got = sha256_digest_stream_from_file(self.path, bufsize=2048)
        except Exception as e:
            self.last_error = "SHA_FAIL:%s" % e
            self.active = False
            return False

        ok = (got == self.expect_sha256)

        self.last_result = {
            "ok": ok,
            "path": self.path,
            "file_id": self.file_id,
            "total": self.total_size,
            "written": self.written,
            "sha256_expect": sha256_hex_from_digest(self.expect_sha256),
            "sha256_got": sha256_hex_from_digest(got),
        }

        # end session
        self.active = False

        if not ok:
            self.last_error = "SHA_MISMATCH"
        else:
            self.last_error = None

        return ok
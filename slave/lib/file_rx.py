# /lib/file_rx.py
import binascii

def sha256_digest_stream_from_file(path: str, bufsize=2048) -> bytes:
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

def sha_hex(digest32: bytes) -> str:
    return binascii.hexlify(digest32).decode()

class FileRx:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.file_id = 0
        self.total = 0
        self.chunk_size = 0
        self.sha_expect = None
        self.path = None
        self.fp = None
        self.written = 0
        self.last_error = None

    def _close(self):
        if self.fp:
            try: self.fp.close()
            except Exception: pass
        self.fp = None

    def _prealloc_fast(self, path: str, total: int):
        try:
            with open(path, "wb") as f:
                if total > 0:
                    f.seek(total - 1)
                    f.write(b"\x00")
            return True
        except Exception:
            return False

    def begin(self, args: dict) -> bool:
        self.last_error = None
        self._close()
        self.reset()

        self.active = True
        self.file_id = int(args["file_id"])
        self.total = int(args["total_size"])
        self.chunk_size = int(args["chunk_size"])
        self.sha_expect = args["sha256"]
        self.path = args["path"]
        self.written = 0

        if not self._prealloc_fast(self.path, self.total):
            # fallback fill zeros
            zero = b"\x00" * 512
            with open(self.path, "wb") as f:
                left = self.total
                while left > 0:
                    n = 512 if left >= 512 else left
                    f.write(zero[:n])
                    left -= n

        try:
            self.fp = open(self.path, "r+b")
            return True
        except Exception as e:
            self.last_error = "OPEN_FAIL:%s" % e
            self.active = False
            return False

    def chunk(self, args: dict) -> bool:
        if not self.active or self.fp is None:
            self.last_error = "NO_ACTIVE"
            return False
        if int(args["file_id"]) != self.file_id:
            self.last_error = "FILE_ID_MISMATCH"
            return False

        off = int(args["offset"])
        data = args["data"] or b""
        if off + len(data) > self.total:
            self.last_error = "OUT_OF_RANGE"
            return False
        try:
            self.fp.seek(off)
            self.fp.write(data)
            self.written += len(data)
            return True
        except Exception as e:
            self.last_error = "WRITE_FAIL:%s" % e
            return False

    def end(self, args: dict) -> bool:
        if int(args["file_id"]) != self.file_id:
            self.last_error = "FILE_ID_MISMATCH"
            return False
        self._close()

        got = sha256_digest_stream_from_file(self.path, bufsize=2048)
        ok = (got == self.sha_expect)
        if not ok:
            self.last_error = "SHA_MISMATCH exp=%s got=%s" % (sha_hex(self.sha_expect), sha_hex(got))
        self.active = False
        return ok
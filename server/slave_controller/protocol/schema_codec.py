# /lib/schema_codec.py
import struct

class BufferReader:
    def __init__(self, data: bytes):
        self.data = data if data else b""
        self.pos = 0

    def remaining(self): return len(self.data) - self.pos
    def read(self, n):
        if self.pos + n > len(self.data):
            raise ValueError("UNDERFLOW")
        b = self.data[self.pos:self.pos+n]
        self.pos += n
        return b
    def take_all(self):
        b = self.data[self.pos:]
        self.pos = len(self.data)
        return b

    def u8(self): return self.read(1)[0]
    def u16(self):
        v = struct.unpack_from("<H", self.data, self.pos)[0]; self.pos += 2; return v
    def u32(self):
        v = struct.unpack_from("<I", self.data, self.pos)[0]; self.pos += 4; return v
    def i16(self):
        v = struct.unpack_from("<h", self.data, self.pos)[0]; self.pos += 2; return v
    def i32(self):
        v = struct.unpack_from("<i", self.data, self.pos)[0]; self.pos += 4; return v

    def str_u16len(self):
        ln = self.u16()
        b = self.read(ln)
        return b.decode("utf-8")

class BufferWriter:
    def __init__(self):
        self.parts = []
    def put(self, b: bytes):
        if b:
            self.parts.append(b)
    def u8(self, v): self.parts.append(bytes((int(v) & 0xFF,)))
    def u16(self, v): self.parts.append(struct.pack("<H", int(v) & 0xFFFF))
    def u32(self, v): self.parts.append(struct.pack("<I", int(v) & 0xFFFFFFFF))
    def i16(self, v): self.parts.append(struct.pack("<h", int(v)))
    def i32(self, v): self.parts.append(struct.pack("<i", int(v)))
    def str_u16len(self, s):
        b = (s if isinstance(s, str) else str(s)).encode("utf-8")
        self.u16(len(b)); self.put(b)
    def bytes_fixed(self, b, ln):
        if b is None: b = b""
        if len(b) != ln:
            raise ValueError("bytes_fixed mismatch")
        self.put(b)
    def build(self): return b"".join(self.parts)

def decode_payload(cmd_def: dict, payload: bytes) -> dict:
    r = BufferReader(payload)
    out = {"_name": cmd_def.get("name"), "_cmd": cmd_def.get("cmd")}
    for f in cmd_def.get("payload", []):
        t = f["type"]; name = f["name"]
        if t == "u8": out[name] = r.u8()
        elif t == "u16": out[name] = r.u16()
        elif t == "u32": out[name] = r.u32()
        elif t == "i16": out[name] = r.i16()
        elif t == "i32": out[name] = r.i32()
        elif t == "str_u16len": out[name] = r.str_u16len()
        elif t == "bytes_fixed": out[name] = r.read(int(f["len"]))
        elif t == "bytes_rest": out[name] = r.take_all()
        else:
            raise ValueError("Unsupported type:%s" % t)
    out["_remain"] = r.remaining()
    return out

def encode_payload(cmd_def: dict, obj: dict) -> bytes:
    w = BufferWriter()
    for f in cmd_def.get("payload", []):
        t = f["type"]; name = f["name"]
        val = obj.get(name)
        if t == "u8": w.u8(val or 0)
        elif t == "u16": w.u16(val or 0)
        elif t == "u32": w.u32(val or 0)
        elif t == "i16": w.i16(val or 0)
        elif t == "i32": w.i32(val or 0)
        elif t == "str_u16len": w.str_u16len(val or "")
        elif t == "bytes_fixed": w.bytes_fixed(val, int(f["len"]))
        elif t == "bytes_rest": w.put(val or b"")
        else:
            raise ValueError("Unsupported type:%s" % t)
    return w.build()
import struct

class SchemaCodec:
    @staticmethod
    def decode(cmd_def: dict, payload: bytes) -> dict:
        """穩定版解碼：優化內存開銷"""
        pos = 0
        payload_len = len(payload)
        out = {"_name": cmd_def.get("name"), "_cmd": cmd_def.get("cmd")}
        
        for f in cmd_def.get("payload", []):
            t, name = f["type"], f["name"]
            if pos >= payload_len and t != "bytes_rest":
                break

            try:
                # 使用 memoryview 能避免在大數據塊(Buffer)傳輸時產生不必要的拷貝
                if t == "u8":
                    out[name] = int(payload[pos]); pos += 1
                elif t == "u16":
                    out[name] = struct.unpack_from("<H", payload, pos)[0]; pos += 2
                elif t == "u32":
                    out[name] = struct.unpack_from("<I", payload, pos)[0]; pos += 4
                elif t == "str_u16len":
                    ln = struct.unpack_from("<H", payload, pos)[0]; pos += 2
                    out[name] = bytes(payload[pos : pos + ln]).decode("utf-8"); pos += ln
                elif t == "bytes_fixed":
                    flen = int(f["len"])
                    # 這裡必須拷貝一份，因為 Parser 的 Buffer 是會變動的
                    out[name] = bytes(payload[pos : pos + flen]); pos += flen
                elif t == "bytes_rest":
                    # 🚀 [修正] 提取剩下的所有數據到 data
                    out[name] = bytes(payload[pos:])
                    pos = payload_len
            except Exception as e:
                print(f"❌ [Codec] Decode field '{name}' error: {e}")
                break
        return out

    @staticmethod
    def encode(cmd_def: dict, obj: dict) -> bytes:
        """嚴格按照 Schema 順序編碼：修復 bytes_rest 錯誤"""
        buf = bytearray()
        
        for f in cmd_def.get("payload", []):
            t, name = f["type"], f["name"]
            val = obj.get(name)
            
            try:
                if t == "u8":
                    buf.append(int(val or 0) & 0xFF)
                elif t == "u16":
                    buf.extend(struct.pack("<H", int(val or 0)))
                elif t == "u32":
                    buf.extend(struct.pack("<I", int(val or 0)))
                elif t == "i16":
                    buf.extend(struct.pack("<h", int(val or 0)))
                elif t == "i32":
                    buf.extend(struct.pack("<i", int(val or 0)))
                elif t == "str_u16len":
                    s = str(val or "").encode("utf-8")
                    buf.extend(struct.pack("<H", len(s)))
                    buf.extend(s)
                elif t == "bytes_fixed":
                    flen = int(f["len"])
                    b = val if val is not None else b"\x00" * flen
                    if len(b) > flen: b = b[:flen]
                    if len(b) < flen: b = b + b"\x00" * (flen - len(b))
                    buf.extend(b)
                elif t == "bytes_rest":
                    # 🚀 [修正] 原本這裡寫成了 decode 的邏輯，現在修復為正確的編碼
                    if val is not None:
                        if isinstance(val, (bytes, bytearray, memoryview)):
                            buf.extend(val)
                        else:
                            # 如果傳入的是 list (如 [1, 2, 3])
                            buf.extend(bytes(val))
            except Exception as e:
                print(f"❌ [Codec] Encode field '{name}' failed: {e}")
                
        return bytes(buf)
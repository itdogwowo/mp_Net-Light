# /lib/app.py
# mp_Net-Light MCU app core
# - schema driven payload decode/encode
# - centralized cmd -> handler registration
# - bus-independent entrypoints (feed bytes from anywhere)

from lib.proto import StreamParser, pack_packet
from lib.schema_loader import SchemaStore, cmd_str_to_int
from lib.dispatch import Dispatcher
from lib.file_rx import FileRx
from lib.schema_codec2 import encode_payload

import ujson as json
import os
import ubinascii


class App:
    def __init__(self, schema_dir="/schema"):
        self.store = SchemaStore()
        self.store.load_dir(schema_dir)

        self.disp = Dispatcher(self.store)
        self.parser = StreamParser(max_len=4096, accept_addr=None)

        # 接收端：FILE 三件套接收器
        self.file_rx = FileRx()

        self._register_handlers()

    # ------------------------------------------------------------
    # Bus entrypoints
    # ------------------------------------------------------------
    def on_rx_bytes(self, data: bytes, ctx=None):
        if ctx is None:
            ctx = {}
        self.parser.feed(data)
        for ver, addr, cmd, payload in self.parser.pop():
            self.disp.dispatch(cmd, payload, ctx)

    # ------------------------------------------------------------
    # Internal helpers: FS tree walker (reused by FS_TREE_GET and snapshot)
    # ------------------------------------------------------------
    def _join_path(self, base, name):
        if base == "/":
            return "/" + name
        if base.endswith("/"):
            return base + name
        return base + "/" + name

    def _is_dir(self, path):
        try:
            os.listdir(path)
            return True
        except Exception:
            return False

    def _walk_tree_lines(self, root, max_depth, include_size, prefix="", depth=0):
        lines = []
        try:
            names = os.listdir(root)
        except Exception as e:
            return ["%s[ERR] %s" % (prefix, e)]

        names.sort()
        for i, name in enumerate(names):
            is_last = (i == len(names) - 1)
            branch = "└─ " if is_last else "├─ "
            next_prefix = prefix + ("   " if is_last else "│  ")

            full = self._join_path(root, name)

            if self._is_dir(full):
                lines.append("%s%s%s/" % (prefix, branch, name))
                if depth + 1 < max_depth:
                    lines.extend(self._walk_tree_lines(full, max_depth, include_size, next_prefix, depth + 1))
            else:
                if include_size:
                    try:
                        sz = os.stat(full)[6]
                        lines.append("%s%s%s (%d)" % (prefix, branch, name, sz))
                    except Exception:
                        lines.append("%s%s%s" % (prefix, branch, name))
                else:
                    lines.append("%s%s%s" % (prefix, branch, name))
        return lines

    # ------------------------------------------------------------
    # Internal helpers: build JSON snapshot file
    # ------------------------------------------------------------
    def build_fs_snapshot_json(self, root_path: str, out_path: str, max_depth: int, include_size: int):
        """
        生成漂亮格式化 JSON snapshot（人眼友善）
        - 直接寫檔（stream write），避免一次組超大字串
        - entries 逐筆輸出，每筆一行（漂亮、易讀）
        """
        if max_depth <= 0:
            max_depth = 1
        if max_depth > 32:
            max_depth = 32

        def json_escape(s: str) -> str:
            # 最小必要 escape：\ 和 "
            return s.replace("\\", "\\\\").replace('"', '\\"')

        def write_entry(f, parent: str, name: str, typ: str, size: int = None, first=False):
            # typ: 'd' or 'f'
            # 以漂亮縮排輸出
            # {"p":"...","n":"...","t":"d","s":123}
            p = json_escape(parent)
            n = json_escape(name)

            if not first:
                f.write(",\n")
            f.write('    {"p":"%s","n":"%s","t":"%s"' % (p, n, typ))
            if size is not None:
                f.write(',"s":%d' % int(size))
            f.write("}")

        def walk(f, parent: str, depth: int, first_entry_flag: list):
            # first_entry_flag 是單元素 list，用來在遞迴中共享「是否第一筆」狀態
            try:
                names = os.listdir(parent)
            except Exception:
                return

            names.sort()
            for name in names:
                full = self._join_path(parent, name)
                if self._is_dir(full):
                    write_entry(f, parent, name, "d", None, first=first_entry_flag[0])
                    first_entry_flag[0] = False
                    if depth + 1 < max_depth:
                        walk(f, full, depth + 1, first_entry_flag)
                else:
                    if include_size:
                        try:
                            sz = os.stat(full)[6]
                        except Exception:
                            sz = 0
                        write_entry(f, parent, name, "f", sz, first=first_entry_flag[0])
                    else:
                        write_entry(f, parent, name, "f", None, first=first_entry_flag[0])
                    first_entry_flag[0] = False

        # 直接輸出漂亮 JSON
        with open(out_path, "w") as f:
            f.write("{\n")
            f.write('  "root": "%s",\n' % json_escape(root_path))
            f.write('  "max_depth": %d,\n' % int(max_depth))
            f.write('  "include_size": %d,\n' % (1 if include_size else 0))
            f.write('  "entries": [\n')

            first_entry_flag = [True]
            walk(f, root_path, 0, first_entry_flag)

            f.write("\n  ]\n")
            f.write("}\n")

    # ------------------------------------------------------------
    # Internal helpers: send any local file via FILE triplet (loopback mode)
    # ------------------------------------------------------------
    def send_file_triplet_loopback(self, src_path: str, dst_path: str, file_id: int, chunk_size: int, ctx: dict):
        """
        把 src_path 以 FILE_BEGIN/CHUNK/END 的封包流形式“送出”
        在離線 loopback 模式下，直接用 ctx["send_loopback"](pkt) 丟回 on_rx_bytes，
        讓接收端 FileRx 把檔案寫到 dst_path
        """
        if "send_loopback" not in ctx:
            print("ERROR: ctx lacks send_loopback")
            return False

        CMD_FILE_BEGIN = cmd_str_to_int("0x2001")
        CMD_FILE_CHUNK = cmd_str_to_int("0x2002")
        CMD_FILE_END   = cmd_str_to_int("0x2003")

        begin_def = self.store.get(CMD_FILE_BEGIN)
        chunk_def = self.store.get(CMD_FILE_CHUNK)
        end_def   = self.store.get(CMD_FILE_END)

        if not (begin_def and chunk_def and end_def):
            print("ERROR: missing file schema")
            return False

        # sha256
        from lib.file_rx import sha256_digest_stream_from_file
        sha = sha256_digest_stream_from_file(src_path, bufsize=2048)

        total = os.stat(src_path)[6]

        begin_payload = encode_payload(begin_def, {
            "file_id": file_id,
            "total_size": total,
            "chunk_size": chunk_size,
            "sha256": sha,
            "path": dst_path
        })

        ctx["send_loopback"](pack_packet(CMD_FILE_BEGIN, begin_payload))

        # chunks
        with open(src_path, "rb") as f:
            off = 0
            buf = bytearray(chunk_size)
            while True:
                try:
                    n = f.readinto(buf)
                except AttributeError:
                    data = f.read(chunk_size)
                    n = len(data)
                    if n:
                        buf[:n] = data

                if not n:
                    break

                chunk_payload = encode_payload(chunk_def, {
                    "file_id": file_id,
                    "offset": off,
                    "data": bytes(buf[:n])
                })
                ctx["send_loopback"](pack_packet(CMD_FILE_CHUNK, chunk_payload))
                off += n

        end_payload = encode_payload(end_def, {"file_id": file_id})
        ctx["send_loopback"](pack_packet(CMD_FILE_END, end_payload))
        return True

    # ------------------------------------------------------------
    # Handlers registration
    # ------------------------------------------------------------
    def _register_handlers(self):
        """
        集中註冊所有 cmd handlers
        """

        # ---- FILE triplet receiver ----
        CMD_FILE_BEGIN = cmd_str_to_int("0x2001")
        CMD_FILE_CHUNK = cmd_str_to_int("0x2002")
        CMD_FILE_END   = cmd_str_to_int("0x2003")

        def h_file_begin(ctx, args):
            ok = self.file_rx.begin(args)
            print("FILE_BEGIN:", "OK" if ok else ("FAIL " + str(self.file_rx.last_error)))

        def h_file_chunk(ctx, args):
            ok = self.file_rx.chunk(args)
            if not ok:
                print("FILE_CHUNK FAIL:", self.file_rx.last_error)

        def h_file_end(ctx, args):
            ok = self.file_rx.end(args)
            print("FILE_END:", "OK" if ok else ("FAIL " + str(self.file_rx.last_error)))

        self.disp.on(CMD_FILE_BEGIN, h_file_begin)
        self.disp.on(CMD_FILE_CHUNK, h_file_chunk)
        self.disp.on(CMD_FILE_END, h_file_end)

        # ---- FS tree (single packet) ----
        CMD_FS_TREE_GET = cmd_str_to_int("0x1205")
        CMD_FS_TREE_RSP = cmd_str_to_int("0x1206")

        def h_fs_tree_get(ctx, args):
            path = args.get("path", "/")
            max_depth = int(args.get("max_depth", 10))
            include_size = int(args.get("include_size", 0))

            if max_depth <= 0:
                max_depth = 1
            if max_depth > 16:
                max_depth = 16

            header = "%s\n" % path
            lines = self._walk_tree_lines(path, max_depth, include_size)
            tree_txt = header + "\n".join(lines)

            if "send_loopback" in ctx:
                rsp_def = self.store.get(CMD_FS_TREE_RSP)
                rsp_payload = encode_payload(rsp_def, {"path": path, "tree": tree_txt})
                ctx["send_loopback"](pack_packet(CMD_FS_TREE_RSP, rsp_payload))

        self.disp.on(CMD_FS_TREE_GET, h_fs_tree_get)

        # ---- FS snapshot as JSON file + FILE triplet return (unified) ----
        CMD_FS_SNAP_GET = cmd_str_to_int("0x1213")

        def h_fs_snap_get(ctx, args):
            root = args.get("path", "/")
            out_path = args.get("out_path", "/fs_snapshot.json")
            max_depth = int(args.get("max_depth", 10))
            include_size = int(args.get("include_size", 1))

            # 1) build snapshot file
            try:
                self.build_fs_snapshot_json(root, out_path, max_depth, include_size)
            except Exception as e:
                print("FS_SNAP_GET build fail:", e)
                return

            # 2) send snapshot via FILE triplet (loopback)
            #    寫入到接收端路徑固定：/rx_snapshot.json
            rx_path = "/rx_snapshot.json"
            ok = self.send_file_triplet_loopback(out_path, rx_path, file_id=99, chunk_size=1024, ctx=ctx)
            if ok:
                print("FS_SNAP_GET: 已生成並回傳 =>", rx_path)
            else:
                print("FS_SNAP_GET: 回傳失敗")

        self.disp.on(CMD_FS_SNAP_GET, h_fs_snap_get)
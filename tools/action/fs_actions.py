# /action/fs_actions.py
from lib.schema_loader import cmd_str_to_int
from lib.schema_codec import encode_payload
from lib.proto import pack_packet
import os
import ujson as json

CMD_FS_TREE_GET = cmd_str_to_int("0x1205")
CMD_FS_TREE_RSP = cmd_str_to_int("0x1206")
CMD_FS_SNAP_GET = cmd_str_to_int("0x1213")

CMD_FILE_BEGIN = cmd_str_to_int("0x2001")
CMD_FILE_CHUNK = cmd_str_to_int("0x2002")
CMD_FILE_END   = cmd_str_to_int("0x2003")


def register(app):

    # ---------- small path utils ----------
    def join_path(base, name):
        if base == "/":
            return "/" + name
        if base.endswith("/"):
            return base + name
        return base + "/" + name

    def is_dir(path):
        try:
            os.listdir(path)
            return True
        except Exception:
            return False

    # ---------- FS_TREE (single packet text) ----------
    def walk_tree_lines(root, max_depth, include_size, prefix="", depth=0):
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

            full = join_path(root, name)
            if is_dir(full):
                lines.append("%s%s%s/" % (prefix, branch, name))
                if depth + 1 < max_depth:
                    lines.extend(walk_tree_lines(full, max_depth, include_size, next_prefix, depth + 1))
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

    def on_tree_get(ctx, args):
        path = args.get("path", "/")
        max_depth = int(args.get("max_depth", 10))
        include_size = int(args.get("include_size", 0))

        if max_depth <= 0: max_depth = 1
        if max_depth > 16: max_depth = 16

        tree_txt = path + "\n" + "\n".join(walk_tree_lines(path, max_depth, include_size))

        if "send_loopback" in ctx:
            rsp_def = app.store.get(CMD_FS_TREE_RSP)
            rsp_payload = encode_payload(rsp_def, {"path": path, "tree": tree_txt})
            ctx["send_loopback"](pack_packet(CMD_FS_TREE_RSP, rsp_payload))

    # ---------- Pretty JSON snapshot (stream write) ----------
    def build_fs_snapshot_json_pretty(root_path, out_path, max_depth, include_size):
        if max_depth <= 0: max_depth = 1
        if max_depth > 32: max_depth = 32

        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')

        def write_entry(f, parent, name, typ, size=None, first=False):
            if not first:
                f.write(",\n")
            f.write('    {"p":"%s","n":"%s","t":"%s"' % (esc(parent), esc(name), typ))
            if size is not None:
                f.write(',"s":%d' % int(size))
            f.write("}")

        def walk(parent, depth, first_flag):
            try:
                names = os.listdir(parent)
            except Exception:
                return
            names.sort()
            for name in names:
                full = join_path(parent, name)
                if is_dir(full):
                    write_entry(f, parent, name, "d", None, first=first_flag[0])
                    first_flag[0] = False
                    if depth + 1 < max_depth:
                        walk(full, depth + 1, first_flag)
                else:
                    if include_size:
                        try:
                            sz = os.stat(full)[6]
                        except Exception:
                            sz = 0
                        write_entry(f, parent, name, "f", sz, first=first_flag[0])
                    else:
                        write_entry(f, parent, name, "f", None, first=first_flag[0])
                    first_flag[0] = False

        with open(out_path, "w") as f:
            f.write("{\n")
            f.write('  "root": "%s",\n' % esc(root_path))
            f.write('  "max_depth": %d,\n' % int(max_depth))
            f.write('  "include_size": %d,\n' % (1 if include_size else 0))
            f.write('  "entries": [\n')
            first_flag = [True]
            walk(root_path, 0, first_flag)
            f.write("\n  ]\n")
            f.write("}\n")

    # ---------- Send local file via FILE triplet (loopback) ----------
    def send_file_triplet_loopback(src_path, dst_path, file_id, chunk_size, ctx):
        if "send_loopback" not in ctx:
            print("ERROR: ctx lacks send_loopback")
            return False

        begin_def = app.store.get(CMD_FILE_BEGIN)
        chunk_def = app.store.get(CMD_FILE_CHUNK)
        end_def   = app.store.get(CMD_FILE_END)
        if not (begin_def and chunk_def and end_def):
            print("ERROR: file schema missing")
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

    # ---------- FS_SNAP_GET (build /fs_snapshot.json and return via file triplet) ----------
    def on_snap_get(ctx, args):
        root = args.get("path", "/")
        out_path = args.get("out_path", "/fs_snapshot.json")
        max_depth = int(args.get("max_depth", 20))
        include_size = int(args.get("include_size", 1))

        try:
            build_fs_snapshot_json_pretty(root, out_path, max_depth, include_size)
        except Exception as e:
            print("FS_SNAP_GET build fail:", e)
            return

        # 回傳到接收端路徑固定（你可改成 args 指定）
        rx_path = "/rx_snapshot.json"
        ok = send_file_triplet_loopback(out_path, rx_path, file_id=99, chunk_size=1024, ctx=ctx)
        if ok:
            print("FS_SNAP_GET: 已生成並回傳 =>", rx_path)
        else:
            print("FS_SNAP_GET: 回傳失敗")

    app.disp.on(CMD_FS_TREE_GET, on_tree_get)
    app.disp.on(CMD_FS_SNAP_GET, on_snap_get)
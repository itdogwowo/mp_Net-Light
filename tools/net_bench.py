import os
import sys
import socket
import struct
import threading
import time
import select


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from slave.lib.proto import Proto, StreamParser
from slave.lib.schema_loader import SchemaStore
from slave.lib.schema_codec import SchemaCodec


def _ws_handshake(conn):
    conn.settimeout(2)
    buf = bytearray()
    while b"\r\n\r\n" not in buf and len(buf) < 8192:
        try:
            part = conn.recv(2048)
        except socket.timeout:
            break
        if not part:
            break
        buf.extend(part)
    req = bytes(buf)
    if b"Upgrade: websocket" not in req:
        try:
            conn.settimeout(None)
        except Exception:
            pass
        return False
    resp = (
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
    )
    conn.send(resp)
    try:
        conn.settimeout(None)
    except Exception:
        pass
    return True


def _ws_send_binary(conn, payload: bytes):
    l = len(payload)
    hdr = bytearray([0x82])
    if l <= 125:
        hdr.append(l)
    elif l <= 65535:
        hdr.append(126)
        hdr.extend(struct.pack(">H", l))
    else:
        hdr.append(127)
        hdr.extend(struct.pack(">Q", l))
    _send_all(conn, memoryview(hdr))
    _send_all(conn, memoryview(payload))

def _send_all(conn, data: memoryview):
    mv = data if isinstance(data, memoryview) else memoryview(data)
    sent = 0
    ln = len(mv)
    while sent < ln:
        try:
            n = conn.send(mv[sent:])
            if n is None:
                n = 0
            if n == 0:
                _, w, _ = select.select([], [conn], [], 1.0)
                if not w:
                    continue
            sent += n
        except (BlockingIOError, InterruptedError):
            _, w, _ = select.select([], [conn], [], 1.0)
            if not w:
                continue
        except (BrokenPipeError, ConnectionResetError):
            raise
        except OSError:
            raise


class WSFrameReader:
    def __init__(self, recv_size=65536):
        self._rx = bytearray()
        self._tmp = bytearray(recv_size)

    def recv_payloads(self, conn):
        out = []
        while True:
            try:
                n = conn.recv_into(self._tmp)
            except (socket.timeout, BlockingIOError):
                break
            except OSError:
                break
            if not n:
                break
            self._rx.extend(self._tmp[:n])

        while True:
            if len(self._rx) < 2:
                return out
            b0 = self._rx[0]
            b1 = self._rx[1]
            opcode = b0 & 0x0F
            fin = (b0 >> 7) & 1
            masked = (b1 >> 7) & 1
            ln7 = b1 & 0x7F
            if fin != 1:
                self._rx.clear()
                return out
            if opcode == 0x8:
                self._rx.clear()
                return out
            if opcode != 0x2:
                self._rx.clear()
                return out

            off = 2
            if ln7 == 126:
                if len(self._rx) < 4:
                    return out
                pl_len = (self._rx[2] << 8) | self._rx[3]
                off = 4
            elif ln7 == 127:
                if len(self._rx) < 10:
                    return out
                pl_len = 0
                for i in range(2, 10):
                    pl_len = (pl_len << 8) | self._rx[i]
                off = 10
            else:
                pl_len = ln7

            if masked:
                if len(self._rx) < off + 4:
                    return out
                mask0 = self._rx[off]
                mask1 = self._rx[off + 1]
                mask2 = self._rx[off + 2]
                mask3 = self._rx[off + 3]
                off += 4
            else:
                mask0 = mask1 = mask2 = mask3 = 0

            end = off + pl_len
            if len(self._rx) < end:
                return out

            payload = bytes(self._rx[off:end]) if masked else bytes(self._rx[off:end])
            if masked and pl_len:
                b = bytearray(payload)
                for i in range(pl_len):
                    m = (mask0, mask1, mask2, mask3)[i & 3]
                    b[i] ^= m
                payload = bytes(b)

            out.append(payload)
            del self._rx[:end]


class NetBenchServer:
    def __init__(self, port=8000, discovery_port=9000, announce_interval_s=0.5, schema_dir=None):
        self.port = port
        self.discovery_port = discovery_port
        self.announce_interval_s = announce_interval_s
        self.running = True
        self.conn = None
        self.addr = None
        self.parser = StreamParser(max_len=65535)
        self.ws = WSFrameReader()
        self.store = SchemaStore(dir_path=schema_dir or f"{PROJECT_ROOT}/slave/schema")
        self._announce_thread = None
        self._udp = None
        self._local_ip = None

    def _get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            try:
                s.close()
            except Exception:
                pass

    def _get_discovery_targets(self, local_ip: str):
        env = os.environ.get("NET_BENCH_DISCOVERY_TARGETS", "").strip()
        if env:
            out = []
            for part in env.split(","):
                ip = part.strip()
                if ip:
                    out.append(ip)
            if out:
                return out

        targets = ["255.255.255.255"]
        if local_ip and local_ip.count(".") == 3:
            p = local_ip.split(".")
            targets.append(".".join([p[0], p[1], p[2], "255"]))
        return targets

    def _announce_loop(self):
        self._local_ip = self._get_local_ip()
        ws_url = f"ws://{self._local_ip}:{self.port}/ws"
        cmd_def = self.store.get(0x1001)
        payload = SchemaCodec.encode(cmd_def, {"server_ip": self._local_ip, "ws_url": ws_url})
        pkt = Proto.pack(0x1001, payload)

        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass

        targets = self._get_discovery_targets(self._local_ip)
        print(
            f"[NET_BENCH] announce ws_url={ws_url} udp_port={self.discovery_port} targets={','.join(targets)}"
        )

        while self.running and self.conn is None:
            for ip in targets:
                try:
                    self._udp.sendto(pkt, (ip, self.discovery_port))
                except Exception:
                    pass
            time.sleep(self.announce_interval_s)

        try:
            self._udp.close()
        except Exception:
            pass
        self._udp = None

    def start(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(1)
        print(f"[NET_BENCH] WS server listening on 0.0.0.0:{self.port}")

        self._announce_thread = threading.Thread(target=self._announce_loop, daemon=True)
        self._announce_thread.start()

        self.conn, self.addr = srv.accept()
        print(f"[NET_BENCH] client connected: {self.addr}")
        if not _ws_handshake(self.conn):
            print("[NET_BENCH] handshake failed")
            return
        self.conn.setblocking(False)

        t = threading.Thread(target=self._rx_loop, daemon=True)
        t.start()

    def _rx_loop(self):
        while self.running and self.conn:
            payloads = self.ws.recv_payloads(self.conn)
            for payload in payloads:
                if payload:
                    self.parser.feed(payload)
                    for _ver, _addr, cmd, pl in self.parser.pop():
                        if cmd == 0x1804:
                            cmd_def = self.store.get(cmd)
                            args = SchemaCodec.decode(cmd_def, pl)
                            self._print_report(args)
            time.sleep(0.001)

    def _print_report(self, args):
        run_id = args.get("run_id")
        elapsed_ms = int(args.get("elapsed_ms", 0))
        total_bytes = int(args.get("total_bytes", 0))
        total_chunks = int(args.get("total_chunks", 0))
        last_seq = int(args.get("last_seq", 0))
        mb_s = 0.0
        if elapsed_ms > 0:
            mb_s = (total_bytes / (1024 * 1024)) / (elapsed_ms / 1000.0)
        print(
            f"[REPORT] run={run_id} elapsed_ms={elapsed_ms} bytes={total_bytes} chunks={total_chunks} last_seq={last_seq} mb_s={mb_s:.2f}"
        )

    def send_cmd(self, cmd, args):
        cmd_def = self.store.get(cmd)
        payload = SchemaCodec.encode(cmd_def, args)
        pkt = Proto.pack(cmd, payload)
        _ws_send_binary(self.conn, pkt)

    def bench(self, run_id=1, seconds=5, chunk_size=65000, report_interval_ms=1000, mode=0):
        if not self.conn:
            return

        data = bytearray(chunk_size)
        for i in range(chunk_size):
            data[i] = i & 0xFF

        print(
            f"[NET_BENCH] start run_id={run_id} seconds={seconds} chunk_size={chunk_size} report_interval_ms={report_interval_ms}"
        )
        print("[NET_BENCH] send: NET_BENCH_START(0x1801)")
        self.send_cmd(0x1801, {"run_id": run_id, "report_interval_ms": report_interval_ms, "mode": mode})

        t0 = time.time()
        seq = 0
        sent_bytes = 0
        last_print = t0

        try:
            while time.time() - t0 < seconds:
                self.send_cmd(0x1802, {"run_id": run_id, "seq": seq, "data": data})
                sent_bytes += chunk_size
                seq += 1

                now = time.time()
                if now - last_print >= 0.5:
                    dt = now - t0
                    mb_s = (sent_bytes / (1024 * 1024)) / dt if dt > 0 else 0
                    print(f"[NET_BENCH] sending seq={seq} bytes={sent_bytes} mb_s={mb_s:.2f}")
                    last_print = now
        except (BrokenPipeError, ConnectionResetError):
            self.running = False
            print("[NET_BENCH] connection closed by client during send")
            return

        print("[NET_BENCH] send: NET_BENCH_STOP(0x1803)")
        self.send_cmd(0x1803, {"run_id": run_id})
        dt = time.time() - t0
        mb_s = (sent_bytes / (1024 * 1024)) / dt if dt > 0 else 0
        print(f"[NET_BENCH] sent_bytes={sent_bytes} seconds={dt:.2f} mb_s={mb_s:.2f}")


def main():
    server = NetBenchServer(port=8000, discovery_port=9000, announce_interval_s=0.5)
    server.start()
    server.bench(run_id=1, seconds=10, chunk_size=65000, report_interval_ms=100, mode=0)
    time.sleep(1)


if __name__ == "__main__":
    main()

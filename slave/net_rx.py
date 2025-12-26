# net_rx.py
import usocket as socket
import time
from proto import StreamParser, parse_one, pack_packet, ADDR_BROADCAST

class RxEngine:
    """
    單核心友好：TCP 控制 + UDP 串流
    - TCP：流式解析 StreamParser
    - UDP：parse_one 單包解析
    """

    def __init__(self, my_addr: int, tcp_port=9000, udp_port=9002):
        self.my_addr = my_addr & 0xFFFF
        self.tcp_port = tcp_port
        self.udp_port = udp_port

        self.tcp_srv = None
        self.tcp_cli = None
        self.tcp_peer = None

        self.udp_sock = None

        # TCP parser：只 yield 給自己 or broadcast 的封包
        self.tcp_parser = StreamParser(max_len=4096, accept_dst=self.my_addr)

        # handlers: cmd -> fn(ver, src, dst, payload, meta, rx)
        self.handlers = {}

        # 記住最後一個 UDP 對端（可用於回覆）
        self.last_udp_peer = None

    def on(self, cmd: int, fn):
        self.handlers[cmd & 0xFFFF] = fn

    def start(self, bind_ip="0.0.0.0"):
        # TCP server
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((bind_ip, self.tcp_port))
        s.listen(1)
        s.setblocking(False)
        self.tcp_srv = s

        # UDP
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.bind((bind_ip, self.udp_port))
        u.setblocking(False)
        self.udp_sock = u

    def _dispatch(self, ver, src, dst, cmd, payload, transport, addr):
        fn = self.handlers.get(cmd)
        if not fn:
            return
        meta = {"transport": transport, "addr": addr}
        fn(ver, src, dst, payload, meta, self)

    def _tcp_accept_if_needed(self):
        if self.tcp_cli is not None:
            return
        try:
            c, addr = self.tcp_srv.accept()
            c.setblocking(False)
            self.tcp_cli = c
            self.tcp_peer = addr
        except OSError:
            pass

    def _tcp_recv(self):
        if self.tcp_cli is None:
            return
        try:
            data = self.tcp_cli.recv(1024)
            if not data:
                self.tcp_cli.close()
                self.tcp_cli = None
                self.tcp_peer = None
                return

            self.tcp_parser.feed(data)
            for ver, src, dst, cmd, payload in self.tcp_parser.pop():
                self._dispatch(ver, src, dst, cmd, payload, transport="tcp", addr=self.tcp_peer)

        except OSError:
            pass

    def _udp_recv(self):
        if self.udp_sock is None:
            return
        try:
            pkt, addr = self.udp_sock.recvfrom(2048)
            if not pkt:
                return

            parsed = parse_one(pkt, max_len=2048)
            if not parsed:
                return

            ver, src, dst, cmd, payload = parsed

            # UDP 目的地址過濾：只收自己 or broadcast
            if not (dst == self.my_addr or dst == ADDR_BROADCAST):
                return

            self.last_udp_peer = addr
            self._dispatch(ver, src, dst, cmd, payload, transport="udp", addr=addr)

        except OSError:
            pass

    def send_tcp(self, cmd, payload=b"", dst=ADDR_BROADCAST):
        """TCP 回包：src=MY_ADDR，dst 可指定"""
        if self.tcp_cli is None:
            return
        pkt = pack_packet(cmd, payload, src=self.my_addr, dst=dst)
        try:
            self.tcp_cli.send(pkt)
        except OSError:
            pass

    def send_udp(self, cmd, payload=b"", addr=None, dst=ADDR_BROADCAST):
        """UDP 回包：addr 是 IP:PORT；dst 是協議內目的地址"""
        if self.udp_sock is None:
            return
        if addr is None:
            addr = self.last_udp_peer
        if addr is None:
            return

        pkt = pack_packet(cmd, payload, src=self.my_addr, dst=dst)
        try:
            self.udp_sock.sendto(pkt, addr)
        except OSError:
            pass

    def poll_once(self):
        self._tcp_accept_if_needed()
        self._tcp_recv()
        self._udp_recv()
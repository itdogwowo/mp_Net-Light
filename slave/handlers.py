# handlers.py
CMD_PING = 0x0001
CMD_PONG = 0x0002

def on_ping(ver, src, dst, payload, meta, rx):
    # 收到 ping，回 pong 給來源 src
    if meta["transport"] == "tcp":
        rx.send_tcp(CMD_PONG, b"pong", dst=src)
    else:
        rx.send_udp(CMD_PONG, b"pong", addr=meta["addr"], dst=src)
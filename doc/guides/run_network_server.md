# main.py 啟動網路監聽（舊 TCP 骨架，參考用）

本文件保留一個「最小 TCP 監聽」骨架，方便做概念驗證或單機測試。

目前專案的 Slave 正式入口是「雙核心 TaskManager + NetBus（WS/UDP）」：
- [slave/main.py](../../slave/main.py)
- [tasks/network.py](../../slave/tasks/network.py)
- [lib/net_bus.py](../../slave/lib/net_bus.py)

## 目標（如果你仍想用 TCP 直接餵封包）

- 啟動 TCP server，等待 master 連線
- 連線後持續 recv()，把 bytes 丟給 parser.feed + parser.pop 或 App.handle_stream

## 最小 TCP 監聽範例（MicroPython）

```python
import usocket as socket
import time
from app import App

TCP_PORT = 9000

def run_tcp_server(bind_ip="0.0.0.0", port=TCP_PORT):
    app = App()
    parser = app.create_parser()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind_ip, port))
    srv.listen(1)
    srv.setblocking(False)

    cli = None
    peer = None

    while True:
        if cli is None:
            try:
                cli, peer = srv.accept()
                cli.setblocking(False)
            except OSError:
                time.sleep_ms(50)
                continue

        try:
            data = cli.recv(1024)
            if not data:
                cli.close()
                cli = None
                peer = None
                continue

            app.handle_stream(parser, data, transport_name="TCP", send_func=cli.send, peer=peer)

        except OSError:
            pass

        time.sleep_ms(2)

run_tcp_server()
```

## 回覆封包（handler → send）

- App.handle_stream 會把 send_func 放進 ctx["send"]  
  [app.py](../../slave/app.py#L34-L46)
- handler 可用 Proto.pack 組包後 ctx["send"](pkt)  
  [proto.py](../../slave/lib/proto.py#L52-L60)

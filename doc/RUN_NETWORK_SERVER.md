# RUN_NETWORK_SERVER.md — main.py 啟動網路監聽（TCP 指令接收）

本文件說明如何把 main.py 從「離線自測」切換成「真正啟動網路監聽接收指令」。

你之前的測試放在 test.py，現在可以完全捨棄：把測試集中到 main.py 的「離線模式」或「網路模式」即可。

---

## 0) 目標
- `main.py` 啟動後：
  - 啟動 TCP server，等待 master 連線
  - 連線後持續 `recv()`，把 bytes 丟給 `app.on_rx_bytes()`
- 你只需要在 master 端用同一協議送封包（SOF/VER/ADDR/CMD/LEN/DATA/CRC16）

---

## 1) main.py 建議支援兩種模式
- MODE=A：離線模式（loopback 自測）
- MODE=B：網路模式（TCP server）

你可以用一個變數切換：

```python
MODE = "net"   # "offline" or "net"
```

---

## 2) main.py（網路監聽骨架）
以下是最小 TCP 監聽範例（MicroPython）：

```python
import usocket as socket
import time
from app import App

MY_ADDR = 0x0002
TCP_PORT = 9000

def run_tcp_server(app: App, bind_ip="0.0.0.0", port=TCP_PORT):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind_ip, port))
    srv.listen(1)
    srv.setblocking(False)

    cli = None
    peer = None

    print("[NET] TCP server listening on %s:%d" % (bind_ip, port))

    while True:
        if cli is None:
            try:
                cli, peer = srv.accept()
                cli.setblocking(False)
                print("[NET] client connected:", peer)
            except OSError:
                time.sleep_ms(50)
                continue

        try:
            data = cli.recv(1024)
            if not data:
                print("[NET] client disconnected:", peer)
                cli.close()
                cli = None
                peer = None
                continue

            # ctx 可放 peer / transport
            ctx = {"transport": "tcp", "peer": peer}
            app.on_rx_bytes(data, ctx=ctx)

        except OSError:
            # no data
            pass

        time.sleep_ms(2)
```

main.py 入口：

```python
def main():
    app = App(schema_dir="/schema")
    run_tcp_server(app)

main()
```

---

## 3) 需要回覆（server->master）怎麼辦？
目前 handler 大多只 print/落盤，不回覆。
如果你要回覆：
- 在 ctx 放入 send 函數（例如 `ctx["send"] = cli.send`）
- handler 內用 `pack_packet()` 組包後 `ctx["send"](pkt)`

建議統一做法：
- 在 action handler 中只產生一個 rsp dict
- 用 schema encoder encode + proto.pack_packet 發回

（此部分可後續再加，不影響先接收與執行）

---

## 4) 與你現有架構如何對接？
- `app = App()` 會載入 schema、註冊 action handlers
- TCP recv 得到 bytes 後直接 `app.on_rx_bytes(data, ctx)`
- 一切 cmd 行為都在 /action 內擴展

---

## 5) test.py 可以怎麼處理？
你之前的測試都在 test.py：
- 現在建議刪除或保留但不再依賴
- 測試：
  - 離線測試 → main.py 的 offline mode
  - 網路測試 → main.py 的 net mode

---

## 6) 常見問題
- JSON schema 解析報錯：檢查 /schema/*.json 是否為合法 JSON（不能空檔）
- 收到封包但沒反應：檢查 cmd 是否在 schema 存在且已在 /action 註冊 handler
- TCP 黏包拆包：由 proto.StreamParser 解決（app.on_rx_bytes 已使用）

---
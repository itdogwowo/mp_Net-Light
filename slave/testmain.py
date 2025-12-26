# main.py
import time
from net_rx import RxEngine
from handlers import CMD_PING, on_ping

MY_ADDR = 0x0002  # 例：此設備地址（可寫死或之後用 CMD 配置）

def main():
    rx = RxEngine(my_addr=MY_ADDR, tcp_port=9000, udp_port=9002)
    rx.on(CMD_PING, on_ping)
    rx.start("0.0.0.0")

    while True:
        rx.poll_once()
        time.sleep_ms(2)

main()
# main.py - 完整版本
import network
import time
from discovery_responder import DiscoveryResponder
from websocket_client import WebSocketClient
from app import App

def setup_network():
    """配置 LAN 網絡"""
    lan = network.LAN(
        mdc=31, mdio=52, phy_addr=1,
        phy_type=network.PHY_IP101, ref_clk=50
    )
    lan.active(True)
    
    print("[Network] 等待 IP 分配...")
    timeout = 10
    while not lan.isconnected() and timeout > 0:
        time.sleep(0.5)
        timeout -= 0.5
    
    if lan.isconnected():
        ip, netmask, gateway, dns = lan.ifconfig()
        print("[Network] 已連接")
        print("  IP: {}".format(ip))
        print("  Netmask: {}".format(netmask))
        print("  Gateway: {}".format(gateway))
        return True
    else:
        print("[Network] 連接失敗")
        return False

def main():
    print("=" * 50)
    print("mp_Net-Light - ESP32-P4 Slave")
    print("=" * 50)
    
    # 1. 設置網絡
    if not setup_network():
        print("網絡初始化失敗,退出")
        return
    
    # 2. 🔥 初始化 App (載入 schema, 註冊 handlers)
    print("\n[Main] 初始化 App...")
    app = App(schema_dir="/schema")
    
    # 3. 創建 WebSocket 客戶端 (傳入 app)
    ws_client = WebSocketClient(app)
    
    # 4. WebSocket 連接回調
    def on_ws_connect_request(url):
        """當收到 DISCOVER 時自動連接 WebSocket"""
        print("[Main] 收到 WebSocket 連接請求: {}".format(url))
        ws_client.connect(url)
    
    # 5. 創建並啟動 UDP 發現響應器
    discovery = DiscoveryResponder(
        listen_port=9000,
        server_port=9001
    )
    discovery.set_ws_callback(on_ws_connect_request)
    discovery.start()
    
    # 6. 主循環
    print("\n[Main] 進入主循環...")
    print("[Main] 等待 Server 發現...")
    
    try:
        while True:
            # 輪詢 UDP 響應器
            discovery.poll()
            
            # 🔥 輪詢 WebSocket 客戶端 (接收 CMD)
            ws_client.poll()
            
            # 其他業務邏輯...
            
            time.sleep(0.01)  # 10ms
            
    except KeyboardInterrupt:
        print("\n[Main] 收到中斷信號")
    finally:
        discovery.stop()
        ws_client.disconnect()
        print("[Main] 程序退出")

if __name__ == '__main__':
    main()
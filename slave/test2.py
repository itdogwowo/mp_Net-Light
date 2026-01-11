# main.py - 主程序入口
import network
import time
from discovery_responder import DiscoveryResponder

# ==================== 網絡配置 ====================
def setup_network():
    """配置 LAN 網絡"""
    lan = network.LAN(
        mdc=31,
        mdio=52,
        phy_addr=1,
        phy_type=network.PHY_IP101,
        ref_clk=50
    )
    lan.active(True)
    
    # 等待 IP 分配
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

# ==================== 主程序 ====================
def main():
    print("=" * 50)
    print("mp_Net-Light - ESP32-P4 Slave")
    print("=" * 50)
    
    # 1. 設置網絡
    if not setup_network():
        print("網絡初始化失敗,退出")
        return
    
    # 2. 啟動 UDP 發現響應器
    discovery = DiscoveryResponder(
        listen_port=9000,
        server_port=9001
    )
    discovery.start()
    
    # 3. 主循環
    print("\n[Main] 進入主循環...")
    try:
        while True:
            # 定期輪詢 UDP 響應器(非阻塞)
            discovery.poll()
            
            # 您的其他業務邏輯...
            
            time.sleep(0.01)  # 10ms 輪詢間隔
            
    except KeyboardInterrupt:
        print("\n[Main] 收到中斷信號")
    finally:
        discovery.stop()
        print("[Main] 程序退出")

# ==================== 啟動 ====================
if __name__ == '__main__':
    main()

# main.py - ESP32-P4 主程序 (完整版)
"""
功能:
1. 網絡初始化 (LAN)
2. UDP 設備發現響應
3. WebSocket 自動連接
4. CMD 協議處理 (STATUS/FILE/FS/STREAM)
5. 離線測試模式
"""
import network
import time
import os
import json
import gc
from machine import unique_id

# ==================== 配置 ====================
MODE = 'network'  # 'test' 或 'network'

# ==================== 工具函數 ====================
def get_mac_address():
    """獲取 MAC 地址作為 Slave ID"""
    uid_bytes = unique_id()
    return "{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}".format(
        uid_bytes[0], uid_bytes[1], uid_bytes[2],
        uid_bytes[3], uid_bytes[4], uid_bytes[5]
    )

def setup_network():
    """配置 LAN 網絡"""
    
#     lan = network.WLAN(network.WLAN.IF_STA)
#     if not lan.active():
#         lan.active(True)
#         lan.connect('', '')
#     print(lan.ipconfig('addr4'))
    lan = network.LAN(
        mdc=31,
        mdio=52,
        phy_addr=1,
        phy_type=network.PHY_IP101,
        ref_clk=50
    )
    lan.active(True)
    print("[Network] 等待 IP 分配...")
    
    timeout = 10
    while not lan.isconnected() and timeout > 0:
        time.sleep(0.5)
        timeout -= 0.5
    
    if lan.isconnected():
        ip, netmask, gateway, dns = lan.ifconfig()
        print("[Network] ✅ 已連接")
        print("  IP: {}".format(ip))
        print("  Netmask: {}".format(netmask))
        print("  Gateway: {}".format(gateway))
        return True
    else:
        print("[Network] ❌ 連接失敗")
        return False

# ==================== 離線測試模式 ====================
def test_mode():
    """離線測試模式 - 測試所有 CMD 功能"""
    print("\n" + "=" * 60)
    print("mp_Net-Light - 離線測試模式")
    print("Slave ID: {}".format(get_mac_address()))
    print("=" * 60)
    
    from app import App
    from lib.proto import pack_packet
    from lib.schema_codec import encode_payload
    from lib.schema_loader import cmd_str_to_int
    
    # 初始化 App
    print("\n[1] 初始化 App (載入 schema, 註冊 handlers)")
    app = App(schema_dir="/schema")
    
    # 設置 ctx (重要:傳入 app)
    ctx = {
        "send_loopback": lambda pkt: app.on_rx_bytes(pkt, ctx=ctx),
        "app": app
    }
    
    # ==================== STATUS 測試 ====================
    print("\n[2] STATUS 指令測試")
    print("-" * 60)
    
    CMD_STATUS_GET = cmd_str_to_int("0x1101")
    CMD_STATUS_RSP = cmd_str_to_int("0x1102")
    CMD_STATUS_UPDATE = cmd_str_to_int("0x1103")
    CMD_STATUS_UPDATE_ACK = cmd_str_to_int("0x1104")
    
    # 註冊回應 handlers
    def h_status_rsp(_ctx, args):
        status_json = args.get("status_json", "{}")
        print("\n📥 收到 STATUS_RSP:")
        try:
            data = json.loads(status_json)
            print("  解析結果:")
            for key, value in data.items():
                print("    {}: {}".format(key, value))
        except:
            print("  Raw: {}".format(status_json[:300]))
    
    def h_update_ack(_ctx, args):
        print("\n📥 收到 STATUS_UPDATE_ACK:")
        print("  success: {}".format(args.get("success")))
        print("  message: {}".format(args.get("message")))
    
    app.disp.on(CMD_STATUS_RSP, h_status_rsp)
    app.disp.on(CMD_STATUS_UPDATE_ACK, h_update_ack)
    
    # 測試 1: 讀取配置
    print("\n[2.1] STATUS_GET (query_type=0 - 讀取配置)")
    cmd_def = app.store.get(CMD_STATUS_GET)
    payload = encode_payload(cmd_def, {"query_type": 0})
    app.on_rx_bytes(pack_packet(CMD_STATUS_GET, payload), ctx=ctx)
    
    # 測試 2: 實時查詢
    print("\n[2.2] STATUS_GET (query_type=1 - 實時查詢)")
    payload = encode_payload(cmd_def, {"query_type": 1})
    app.on_rx_bytes(pack_packet(CMD_STATUS_GET, payload), ctx=ctx)
    
    # 測試 3: 混合模式
    print("\n[2.3] STATUS_GET (query_type=2 - 混合模式)")
    payload = encode_payload(cmd_def, {"query_type": 2})
    app.on_rx_bytes(pack_packet(CMD_STATUS_GET, payload), ctx=ctx)
    
    # 測試 4: 更新配置
    print("\n[2.4] STATUS_UPDATE (更新配置)")
    new_config = {
        "server_ip": "10.161.92.127",
        "server_port": 8000,
        "slave_id": get_mac_address(),
        "pixel_count": 400,
        "auto_connect": True
    }
    cmd_def = app.store.get(CMD_STATUS_UPDATE)
    payload = encode_payload(cmd_def, {"config_json": json.dumps(new_config)})
    app.on_rx_bytes(pack_packet(CMD_STATUS_UPDATE, payload), ctx=ctx)
    
    # 測試 5: 驗證更新
    print("\n[2.5] 驗證更新後的配置")
    cmd_def = app.store.get(CMD_STATUS_GET)
    payload = encode_payload(cmd_def, {"query_type": 0})
    app.on_rx_bytes(pack_packet(CMD_STATUS_GET, payload), ctx=ctx)
    
    # ==================== 記憶體報告 ====================
    print("\n[3] 記憶體報告")
    print("-" * 60)
    gc.collect()
    print("  Free RAM: {} bytes".format(gc.mem_free()))
    print("  Allocated: {} bytes".format(gc.mem_alloc()))
    
    print("\n" + "=" * 60)
    print("離線測試完成")
    print("=" * 60)

# ==================== 網絡模式 ====================
def network_mode():
    """網絡模式 - UDP 發現 + WebSocket + CMD 處理"""
    print("\n" + "=" * 60)
    print("mp_Net-Light - ESP32-P4 Slave")
    print("=" * 60)
    
    # 1. 設置網絡
    if not setup_network():
        print("網絡初始化失敗, 退出")
        return
    
    # 2. 初始化 App
    from app import App
    app = App(schema_dir="/schema")
    print("[Main] App 已初始化")
    
    # 🔥 讀取 system_status.json 獲取 Server 配置
    from action.status_actions import SYSTEM_STATUS
    server_ip = SYSTEM_STATUS.get("server_ip", "10.10.1.27")
    server_port = SYSTEM_STATUS.get("server_port", 8000)
    auto_connect = SYSTEM_STATUS.get("auto_connect", False)
    
    print("[Main] 配置:")
    print("  Server: {}:{}".format(server_ip, server_port))
    print("  自動連接: {}".format(auto_connect))
    
    # 3. 導入模組
    from discovery_responder import DiscoveryResponder
    
    ws_client = None
    has_ws = False
    
    try:
        from websocket_client import WebSocketClient
        has_ws = True
        print("[Main] ✅ WebSocket 模組已載入")
    except Exception as e:
        print("[Main] ⚠️ WebSocket 模組載入失敗: {}".format(e))
    
    # 4. 創建 DiscoveryResponder
    discovery = DiscoveryResponder(
        listen_port=9000,
        server_port=9001
    )
    
    slave_id = discovery.slave_id
    print("[Main] Slave ID: {}".format(slave_id))
    
    # 5. 創建 WebSocket 客戶端
    if has_ws:
        ws_client = WebSocketClient(app)
        print("[Main] ✅ WebSocket 客戶端已創建")
        
        def on_ws_connect_request(url):
            """收到 UDP 發現時連接"""
            print("[Main] 📡 收到 WebSocket 連接請求")
            print("[Main] URL: {}".format(url))
            ws_client.connect(url)
        
        discovery.set_ws_callback(on_ws_connect_request)
        print("[Main] ✅ WebSocket 回調已設置")
        
        # 🔥 如果啟用自動連接,立即嘗試連接
        if auto_connect and server_ip and server_ip != "0.0.0.0":
            auto_url = "ws://{}:{}/ws/slave/{}".format(
                server_ip, server_port, slave_id
            )
            print("[Main] 🔄 自動連接模式已啟用")
            print("[Main] 嘗試連接: {}".format(auto_url))
            ws_client.connect(auto_url)
    else:
        print("[Main] ⚠️ WebSocket 功能不可用")
    
    # 6. 啟動 UDP 發現響應器
    discovery.start()
    
    # 7. 主循環
    print("\n[Main] 進入主循環...")
    print("提示:")
    print("  - 支援自動重連 (斷線後每 30 秒嘗試)")
    print("  - 按 Ctrl+C 退出")
    print("-" * 60)
    temp = True
    try:
        last_heartbeat = time.ticks_ms()
        last_reconnect_attempt = time.ticks_ms()
        last_Stream = time.ticks_ms()
        reconnect_interval = 30000  # 30 秒嘗試重連一次
        
        _Stream = 0
        
        while True:
            now = time.ticks_ms()
            
            # 輪詢 UDP 響應器
            discovery.poll()
            
            # 輪詢 WebSocket 客戶端
            if ws_client:
                ws_client.poll()
                
                # 🔥 自動重連邏輯
                if not ws_client.connected and auto_connect:
                    if time.ticks_diff(now, last_reconnect_attempt) >= reconnect_interval:
                        if server_ip and server_ip != "0.0.0.0":
                            auto_url = "ws://{}:{}/ws/slave/{}".format(
                                server_ip, server_port, slave_id
                            )
                            print("[Main] 🔄 嘗試自動重連...")
                            ws_client.connect(auto_url)
                        last_reconnect_attempt = now
            
            # 每 10 秒顯示心跳
            if time.ticks_diff(now, last_heartbeat) > 10000:
                gc.collect()
                print("[Main] 💓 心跳: RAM={} KB, WS={}".format(
                    gc.mem_free() // 1024,
                    "已連接" if (ws_client and ws_client.connected) else "未連接"
                ))
                last_heartbeat = now
            
            # 🔥 您要的 Stream 狀態檢查
            from action.stream_actions import is_streaming
            
            if is_streaming():
                
                if not temp:
                    print("[Main] 🎨 Stream 激活中")
                
                    temp = True
                # Stream 激活時的邏輯
                _Stream = time.ticks_ms()
                if time.ticks_diff(_Stream, last_heartbeat) => 25:
                    last_heartbeat = _Stream
                    
                
                    _Stream = _Stream+1
            else:
                # Stream 未激活
                if temp:
                    print("[Main] 💤 Stream 未激活")
                    _Stream = 0
                    temp = False
            
            # 控制循環頻率 (10ms)
            time_gap = time.ticks_diff(time.ticks_ms(), now)
            if time_gap < 10:
                time.sleep_ms(10 - time_gap)
    
    except KeyboardInterrupt:
        print("\n[Main] 收到中斷信號")
    finally:
        discovery.stop()
        if ws_client:
            ws_client.disconnect()
        print("[Main] 程序退出")


# ==================== 主入口 ====================
def main():
    """主程序入口"""
    print("\n")
    print("╔════════════════════════════════════════╗")
    print("║      mp_Net-Light ESP32-P4 Slave       ║")
    print("╚════════════════════════════════════════╝")
    
    if MODE == 'test':
        test_mode()
    elif MODE == 'network':
        network_mode()
    else:
        print("❌ 未知模式: {}".format(MODE))

# ==================== 啟動 ====================
if __name__ == '__main__':
    main()

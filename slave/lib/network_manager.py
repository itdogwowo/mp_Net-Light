import network
import time
import machine, webrepl
from lib.dispatch import dprint

# 定義 Active Mode 常量
MODE_OFF = 0
MODE_ALWAYS_ON = 1
MODE_BOOT_ONLY = 2

class NetworkManager:
    """
    統一網絡接口管理器
    職責:
    - 管理多個網絡接口 (LAN/WiFi)
    - 處理不同的 Active Mode (長期開啟/限時開啟)
    - 統一管理 WebREPL
    - 支持 RMII LAN 和 SPI LAN
    """
    def __init__(self, sys_bus):
        self.bus = sys_bus
        self.interfaces = {}  # {'lan': obj, 'wifi': obj}
        self.active_modes = {} # {'lan': 1, 'wifi': 2}
        self.boot_time = time.time()
        self.webrepl_started = False
        
        # 狀態追蹤
        self._state = {
            "connected_interfaces": set(), # 當前已連接的接口名稱集合
            "last_check": 0
        }

    def init_from_config(self):
        """從 bus.shared 讀取配置並初始化"""
        net_cfg = self.bus.shared.get('Network', {})
        
        # 1. 初始化 LAN
        lan_cfg = net_cfg.get('lan')
        if lan_cfg:
            self._init_lan(lan_cfg)
            
        # 2. 初始化 WiFi
        wifi_cfg = net_cfg.get('wifi')
        if wifi_cfg:
            self._init_wifi(wifi_cfg)
            
        # 3. 初始連接檢查
        self.check_network(force=True)

    def _init_lan(self, config):
        """初始化 LAN 接口 (支持 RMII 和 SPI)"""
        mode = config.get('active_mode', MODE_ALWAYS_ON)
        if not config.get('enable', False) or mode == MODE_OFF:
            return

        self.active_modes['lan'] = mode
        
        try:
            # 獲取 GPIO 配置
            gpio_cfg = config.get('GPIO', {})
            
            # 判斷驅動類型
            # 優先檢查 driver 字段，其次檢查 GPIO['spi'] 是否有效
            driver_type = config.get('driver', '').upper()
            spi_idx = gpio_cfg.get('spi', -1)
            
            is_spi = (driver_type == 'W5500' or driver_type == 'SPI') or (spi_idx >= 0 and driver_type != 'RMII')
            
            if is_spi:
                # SPI LAN (W5500)
                dprint("🔌 初始化 SPI LAN (W5500)...")
                spi_list = self.bus.get_service("spi_list")
                if not spi_list:
                    raise Exception("SPI service not available")
                
                if spi_idx < 0 or spi_idx >= len(spi_list):
                    raise Exception(f"Invalid SPI bus index: {spi_idx}")
                
                spi = spi_list[spi_idx]
                
                # 檢查 CS/RST 引腳 (從 GPIO 讀取)
                cs_pin_num = gpio_cfg.get('cs', -1)
                rst_pin_num = gpio_cfg.get('rst', -1)
                
                if cs_pin_num < 0 or rst_pin_num < 0:
                     raise Exception("Invalid CS/RST pin for SPI LAN")

                cs_pin = machine.Pin(cs_pin_num)
                rst_pin = machine.Pin(rst_pin_num)
                
                # 初始化 WIZNET5K
                lan = network.WIZNET5K(spi, cs_pin, rst_pin)
                lan.active(True)
                
                # 如果有靜態 IP 配置
                if config.get('static_ip'):
                    lan.ifconfig(tuple(config['static_ip']))
                    
                self.interfaces['lan'] = lan
                dprint("✓ SPI LAN 已初始化")
                
            else:
                # RMII LAN (原生 ETH)
                dprint("🔌 初始化 RMII LAN...")
                # 處理配置列表或單一配置
                eth_cfg = config
                if 'list' in config: # 兼容舊結構
                    eth_cfg = config['list'][0]
                
                # 構建參數
                phy_type = eth_cfg.get('phy_type', network.PHY_LAN8720)
                # 處理 phy_type 字符串轉常量 (如果是字符串)
                if isinstance(phy_type, str):
                    if "IP101" in phy_type: phy_type = network.PHY_IP101
                    else: phy_type = network.PHY_LAN8720
                
                lan = network.LAN(
                    mdc=machine.Pin(eth_cfg['GPIO']['mdc']),
                    mdio=machine.Pin(eth_cfg['GPIO']['mdio']),
                    ref_clk=machine.Pin(eth_cfg['GPIO']['ref_clk']),
                    phy_addr=eth_cfg['phy_addr'],
                    phy_type=phy_type
                )
                lan.active(True)
                self.interfaces['lan'] = lan
                dprint("✓ RMII LAN 已初始化")
                
        except Exception as e:
            dprint(f"✗ LAN 初始化失敗: {e}")

    def _init_wifi(self, config):
        """初始化 WiFi 接口"""
        if not hasattr(network, 'WLAN'):
            dprint("⚠️ 此固件/硬體不支持 WLAN，跳過 WiFi 初始化")
            return

        mode = config.get('active_mode', MODE_BOOT_ONLY)
        if not config.get('enable', False) or mode == MODE_OFF:
            return

        self.active_modes['wifi'] = mode
        # 讀取超時設定 (預設 300 秒)
        self.wifi_timeout = config.get('timeout', 300)
        
        try:
            dprint("📡 初始化 WiFi...")
            wlan = network.WLAN(network.STA_IF)
            wlan.active(True)
            
            # 設置 mDNS 名稱 (如果支持)
            if hasattr(wlan, 'config') and 'mdns_name' in config:
                try:
                    wlan.config(mdns_name=config['mdns_name'])
                except:
                    pass
            
            # 連接
            ssid = config.get('ssid')
            password = config.get('password') or config.get('password_pw') or config.get('ssid_pw') 
            
            if ssid:
                if not wlan.isconnected():
                    dprint(f"   連接到: {ssid}")
                    wlan.connect(ssid, password)
                    # 簡單的連接等待與重試邏輯
                    for _ in range(5):
                        if wlan.isconnected(): break
                        time.sleep(1)
                    
                    if not wlan.isconnected():
                        dprint("   ⚠️ WiFi 連接超時/失敗")
                        try:
                            scan_res = wlan.scan()
                            dprint("   🔍 掃描到的網絡:")
                            for ap in scan_res:
                                # ssid, bssid, channel, RSSI, authmode, hidden
                                dprint(f"     - {ap[0].decode('utf-8', 'ignore')} (RSSI: {ap[3]})")
                        except Exception as scan_err:
                            dprint(f"   🔍 掃描失敗: {scan_err}")
                else:
                    dprint(f"   已連接到 WiFi")
            
            self.interfaces['wifi'] = wlan
            dprint("✓ WiFi 接口已就緒")
            
        except Exception as e:
            dprint(f"✗ WiFi 初始化失敗: {e}")

    def check_network(self, force=False):
        """
        週期性檢查網絡狀態
        在主循環中調用
        """
        now = time.time()
        if not force and now - self._state['last_check'] < 1.0: # 限制檢查頻率 1Hz
            return bool(self._state['connected_interfaces'])
            
        self._state['last_check'] = now
        
        current_connected = set()
        
        # 1. 檢查所有接口
        for name, iface in self.interfaces.items():
            mode = self.active_modes.get(name, MODE_OFF)
            
            # 處理 MODE_BOOT_ONLY 的超時關閉
            if mode == MODE_BOOT_ONLY:
                # 獲取配置的超時時間，預設 300 秒 (5 分鐘)
                timeout = getattr(self, 'wifi_timeout', 300)
                if now - self.boot_time > timeout: 
                    if iface.active():
                        dprint(f"💤 {name.upper()} 達到運行時間限制 ({timeout}s)，關閉接口")
                        iface.active(False)
                    continue
            
            try:
                is_connected = False
                if hasattr(iface, 'isconnected'):
                    is_connected = iface.isconnected()
                elif hasattr(iface, 'status'): # W5500 sometimes uses status
                    is_connected = (iface.status() == 2) # LINK_UP
                
                if is_connected:
                    current_connected.add(name)
                    # 如果之前沒連接，現在連接了
                    if name not in self._state['connected_interfaces']:
                        self._on_interface_up(name, iface)
                else:
                    # 自動重連邏輯 (僅對 MODE_ALWAYS_ON)
                    if mode == MODE_ALWAYS_ON and name == 'wifi':
                        # WiFi 斷線重連通常由系統自動處理，但這裡可以加入額外邏輯
                        pass
                        
            except Exception as e:
                dprint(f"⚠ 檢查 {name} 狀態錯誤: {e}")

        # 更新狀態
        self._state['connected_interfaces'] = current_connected
        
        # 2. WebREPL 管理
        # 只要有任一接口連接，就確保 WebREPL 開啟
        if current_connected and not self.webrepl_started:
            self._start_webrepl()
            
        return bool(current_connected)

    def _on_interface_up(self, name, iface):
        """當接口連接成功時"""
        try:
            cfg = iface.ifconfig()
            dprint(f"🌐 {name.upper()} 連接成功 | IP: {cfg[0]}")
        except:
            dprint(f"🌐 {name.upper()} 連接成功")

    def _start_webrepl(self):
        """啟動 WebREPL"""
        try:
            # 嘗試從 config 讀取密碼，否則使用默認
            # 注意: webrepl.start() 在某些版本可能不支持參數，需依賴 webrepl_cfg.py
            # 這裡我們嘗試傳入 password 參數 (MicroPython 標準庫通常支持)
            webrepl.start(password='12345678') 
            self.webrepl_started = True
            dprint("💻 WebREPL 服務已啟動")
        except Exception as e:
            dprint(f"✗ WebREPL 啟動失敗: {e}")

    def get_active_interface(self):
        """獲取當前首選的活躍接口 (根據優先級)"""
        priority = self.bus.shared.get('Network', {}).get('priority', ['lan', 'wifi'])
        connected = self._state['connected_interfaces']
        
        for name in priority:
            if name in connected:
                return self.interfaces[name]
        
        # 如果優先級列表中的都不在，返迴任意一個
        if connected:
            return self.interfaces[list(connected)[0]]
            
        return None

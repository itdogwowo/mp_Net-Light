from lib.ESP_Boot import *
from lib.LEDController import *
from lib.ConfigManager import *
from lib.sys_bus import bus



def init_lan(sysBus):
    """初始化 LAN 硬件，但不阻塞等待連接"""
    # 這裡保持你的硬體配置
    config = sysBus.shared['ETH_Network']
    lan = network.LAN(mdc=config['list'][0]['GPIO']['mdc'], mdio=config['list'][0]['GPIO']['mdio'],
                      ref_clk=config['list'][0]['GPIO']['ref_clk'], phy_addr=config['list'][0]['phy_type'],
                      phy_type=network.PHY_IP101 )
    lan.active(True)
    sysBus.register_service("lan", lan)
    return


init_lan(bus)

print(bus.get_service("lan"))
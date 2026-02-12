from lib.ESP_Boot import *
from lib.LEDController import *
from lib.ConfigManager import *
from lib.sys_bus import bus



def init_lan(sysBus):
    """初始化 LAN 硬件，但不阻塞等待連接"""
    # 這裡保持你的硬體配置
    config = sysBus.shared['ETH_Network']
    if config['enable']:
        for i in config['list']:
            lan = network.LAN(mdc=i['GPIO']['mdc'], mdio=i['GPIO']['mdio'],
                          ref_clk=i['GPIO']['ref_clk'], phy_addr=i['phy_addr'],
                          phy_type=i['phy_type'] )
            
        lan.active(True)
        sysBus.register_service("lan", lan)
    return

def init_bus(sysBus):
    import machine
    # 這裡保持你的硬體配置
    SPI_config = sysBus.shared['SPI']
    spi_list = []
    if SPI_config['enable']:
        for i in SPI_config['list']:
            spi = machine.SPI(i['id'],
                baudrate=i['baudrate'],
                polarity=i['polarity'],
                phase=i['phase'],
                sck=machine.Pin(i['GPIO']['sck']) if i['GPIO']['sck'] else None ,
                mosi=machine.Pin(i['GPIO']['mosi']) if i['GPIO']['mosi'] else None ,
                miso=machine.Pin(i['GPIO']['miso']) if i['GPIO']['miso'] else None
            )
            spi_list.append(spi)            
            
        print(SPI_config)
        sysBus.register_service("spi_list", spi_list)
    return

def init_led(sysBus):
    # 這裡保持你的硬體配置

    return



init_lan(bus)
init_bus(bus)
init_led(bus)

sss = bus.get_service("spi_list")
print(bus.get_service("lan"))
print(bus.get_service("spi_list"))
# bus.shared['ETH_Network']
from lib.ESP_Boot import *
from lib.LEDController import *
from lib.ConfigManager import *
from lib.sys_bus import bus
from lib.network_manager import NetworkManager
import machine, os


def exists(path):
    try:
        os.stat(path)
    except OSError:
        return False
    return True


def init_network_manager(sysBus):
    """使用 NetworkManager 統一初始化網絡"""
    try:
        net_cfg = sysBus.shared.get("Network") or {}
        if not int(net_cfg.get("enable", 1) or 0):
            return
        nm = NetworkManager(sysBus)
        nm.init_from_config()
        sysBus.register_service("network_manager", nm)
        
        # 兼容性註冊：如果 LAN 存在，註冊為 "lan" 服務
        if 'lan' in nm.interfaces:
            sysBus.register_service("lan", nm.interfaces['lan'])
            
    except Exception as e:
        print(f"❌ Network Init Error: {e}")
    return

def init_bus(sysBus):
    
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
        sysBus.register_service("spi_list", spi_list)
        
    I2C_config = sysBus.shared['I2C']
    i2c_list = []
    if I2C_config['enable']:
        for i in I2C_config['list']:
            i2c = machine.I2C(i['id'],
                freq=i['freq'] if i['freq'] else None,
                scl=machine.Pin(i['GPIO']['scl']) if i['GPIO']['scl'] else None ,
                sda=machine.Pin(i['GPIO']['sda']) if i['GPIO']['sda'] else None 
            )
            i2c_list.append(i2c)            
        sysBus.register_service("i2c_list", i2c_list)
        
        
    return

def init_led(sysBus):
    
    PCA9685_config = sysBus.shared['PCA9685']
    pca9685_list = []
    if PCA9685_config['enable']:
        for i in PCA9685_config['list']:
            if sysBus.shared['I2C']['enable']:
                try:
                    i2c_list = sysBus.get_service("i2c_list")
                    for i2c in i2c_list:
                        devices = i2c.scan()
                        print(f"I2C Scan found: {[hex(d) for d in devices]}")
                        for addr in devices:
                            try:
                                if addr != 112:
                                    pca = PCA9685(i2c, address=addr)
                                    pca.freq(1000)
                                    # 建立符合精簡版接口的控制器
                                    pca9685_list.append(LEDController('i2c_LED', {'led_IO': pca, 'Q': 16, 'order': 'W'}))
                            except Exception as e:
                                print(f"❌ PCA9685 at {hex(addr)} error: {e}")
#                     pca = PCA9685(i2c_list[i['GPIO']['i2c']], address=i['address'])
#                     pca.freq(1000)
#                     pca9685_list.append(LEDController('i2c_LED', {'led_IO': pca, 'Q': 16, 'order': 'W'}))
                except Exception as e:
                    print(f"❌ PCA9685 at {hex(i['address'])} error: {e}")
        sysBus.register_service("pca9685_list", pca9685_list)
    
    
    WS2812_config = sysBus.shared['WS2812']
    ws2812_list = []
    if WS2812_config['enable']:
        import neopixel
        for i in WS2812_config['list']:
            pixel = neopixel.NeoPixel(machine.Pin(i['GPIO'], machine.Pin.OUT),i['Q'])
            ws2812_list.append(LEDController('WS2812', {'led_IO': pixel, 'Q': i['Q'], 'order': i['order']}))
            
        sysBus.register_service("ws2812_list", ws2812_list)
        
        
    APA102_config = sysBus.shared['APA102']
    apa1022_list = []
    if APA102_config['enable']:
        if sysBus.shared['SPI']['enable']:
            for i in APA102_config['list']:
                try:
                    spi_list = sysBus.get_service("spi_list")
                    apa = APA102(spi_list[i['GPIO']['spi']], num_leds=i['Q'])
                    apa1022_list.append(LEDController('APA102', {'led_IO': apa, 'Q': i['Q'], 'order': i['order']}))
                except Exception as e:
                    print(f"❌ APA102 at SPI ID {i['GPIO']['spi']} error: {e}")
                        
        sysBus.register_service("apa1022_list", apa1022_list)
            
    sysBus.register_service("led_list", apa1022_list + ws2812_list + pca9685_list)
    return

def init_st(sysBus):
    try:
        st_LED = LEDStreamer(sysBus.get_service("led_list"))
        st_LED.show_all()
        sysBus.register_service("st_LED", st_LED)
    except Exception as e:
        print(f"❌ st_LED init error: {e}")
    return


def init_display(sysBus):
    cfg = sysBus.shared.get("TFT") or sysBus.shared.get("Display") or {}
    if not cfg.get("enable"):
        return
    try:
        import machine
        import lib.TFT as tft_mod
        dp = None
        dp_tft = {}
        dp_path = cfg.get("dp_config_path") or ""
        if dp_path:
            try:
                import ujson
                with open(dp_path, "r") as f:
                    dp = ujson.load(f) or {}
                dp_tft = dp.get("tft") if isinstance(dp, dict) else {}
                if not isinstance(dp_tft, dict):
                    dp_tft = {}
            except Exception:
                dp = None
                dp_tft = {}

        gpio = cfg.get("GPIO") or {}
        spi_idx = int(gpio.get("spi", 0) or 0)
        spi_list = sysBus.get_service("spi_list") or []
        if spi_idx < 0 or spi_idx >= len(spi_list):
            raise ValueError("invalid spi index")

        dc_pin = gpio.get("dc", None)
        cs_pin = gpio.get("cs", None)
        rst_pin = gpio.get("rst", None)
        if dc_pin is None or cs_pin is None or rst_pin is None:
            raise ValueError("missing TFT GPIO: dc/cs/rst")
        dc = machine.Pin(int(dc_pin))
        cs = machine.Pin(int(cs_pin))
        rst = machine.Pin(int(rst_pin))

        driver = str(cfg.get("driver") or dp_tft.get("driver") or "ST7789")
        cls = getattr(tft_mod, driver, None)
        if cls is None:
            raise ValueError("unknown display driver")

        width = cfg.get("width", None)
        height = cfg.get("height", None)
        if width is None:
            width = dp_tft.get("width", None)
        if height is None:
            height = dp_tft.get("height", None)

        width = int(width or 240)
        height = int(height or 240)
        rotation = int(cfg.get("rotation", dp_tft.get("rotation", 0) or 0) or 0)
        color_order = str(cfg.get("color_order") or dp_tft.get("color_order") or "RGB")
        invert = bool(int(cfg.get("invert", dp_tft.get("invert", 0) or 0) or 0))

        lcd = cls(spi_list[spi_idx], dc, cs, rst, width, height, rotation=rotation, color_order=color_order, invert=invert)

        bl_pin = int(gpio.get("bl", -1) or -1)
        if bl_pin >= 0:
            bl_invert = bool(int(gpio.get("bl_invert", 0) or 0))
            bl = machine.Pin(bl_pin, machine.Pin.OUT, value=(0 if bl_invert else 1))
            sysBus.register_service("lcd_bl", bl)

        init_fill = cfg.get("init_fill", None)
        if init_fill is None:
            init_fill = dp_tft.get("init_fill", 0)
        if init_fill is not None and init_fill != 0 and init_fill is not False:
            try:
                fill_val = init_fill
                if fill_val is True:
                    fill_val = (0, 0, 0)
                if isinstance(fill_val, list) and len(fill_val) == 3:
                    fill_val = (int(fill_val[0]), int(fill_val[1]), int(fill_val[2]))
                lcd.fill(fill_val)
            except Exception:
                pass

        sysBus.register_service("lcd", lcd)
        sysBus.register_service("tft", lcd)
    except Exception as e:
        print(f"❌ Display init error: {e}")
    return


def init_sd(sysBus):
    config = sysBus.shared['SDcard']
    _phat = ''
    if config['enable'] and not exists(config["phat"]):
        try:
            from esp32 import LDO
            _phat = config["phat"]
            ldo = LDO(config['LDO']['id'], config['LDO']['mv'], adjustable=True)
            sd = machine.SDCard(slot=config['config']['slot'], width=config['config']['width'],
                sck=config['GPIO']['sck'], cmd=config['GPIO']['cmd'],
                data=config['GPIO']['data'],
                freq=config['config']['freq'])
            os.mount(sd, f'{config["phat"]}')
        except Exception as e:
            print(f"❌ SD card init error: {e}")
            
    sysBus.register_service("data_Phat", _phat)
    return

init_network_manager(bus)
init_bus(bus)
init_display(bus)
init_led(bus)
init_st(bus)
init_sd(bus)

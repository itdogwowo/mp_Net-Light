# lib/sys_bus.py

class SysBus:
    def __init__(self):
        self._services = {}
        self._providers = {}
        self.shared = {"engine_run": True} 
        self.slave_id = "UNKNOWN"

    def register_service(self, name, obj):
        if name in self._services: return False
        self._services[name] = obj
        return True

    def get_service(self, name):
        return self._services.get(name)

    def register_provider(self, key, func):
        if key in self._providers: return False
        self._providers[key] = func
        return True

    # 🚀 [新增] 獲取單個 Provider 的實時數據
    def get_data(self, key):
        if key in self._providers:
            return self._providers[key]()
        return None

    def get_metrics(self):
        """一次性獲取所有 Provider 數據"""
        res = {k: f() for k, f in self._providers.items()}
        res["slave_id"] = self.slave_id
        return res

bus = SysBus()
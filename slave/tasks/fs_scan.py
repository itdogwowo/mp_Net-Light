from lib.task import Task
from lib.sys_bus import bus
from lib.fs_manager import fs


class FSScanTask(Task):
    def loop(self):
        if bus.shared.get("fs_scan_requested"):
            fs.perform_scan()
            bus.shared["fs_scan_requested"] = False


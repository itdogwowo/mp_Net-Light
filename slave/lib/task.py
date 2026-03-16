class Task:
    def __init__(self, name, ctx):
        self.name = name
        self.ctx = ctx
        self.running = False
        self.run_once = False
        self.boot_done = False

    def on_boot(self):
        self.boot_done = True
        return True

    def on_start(self):
        self.running = True

    def loop(self):
        pass

    def on_stop(self):
        self.running = False

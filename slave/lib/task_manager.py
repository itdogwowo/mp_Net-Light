import gc
import time
from lib.sys_bus import bus

class TaskManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.tasks = {}       # {name: TaskInstance} (Singleton per name)
        self.task_classes = {} # {name: TaskClass}
        self.config = {}      # {name: (core0_affinity, core1_affinity)}
        self.active_tasks = {0: {}, 1: {}} # {core_id: {name: TaskInstance}}
        
        # Register to bus
        bus.register_service("task_manager", self)

    def register_task(self, name, task_cls, default_affinity=(0, 0), run_once=False):
        self.task_classes[name] = task_cls
        self.config[name] = default_affinity
        self._run_once_flags = getattr(self, '_run_once_flags', {})
        self._run_once_flags[name] = run_once
        print(f"Task [{name}] registered with affinity {default_affinity}")

    def set_affinity(self, name, affinity):
        """
        Dynamically update affinity.
        affinity: (core0, core1). e.g., (1, 0) -> Run on Core 0 only.
        Cannot be (1, 1).
        """
        if affinity == (1, 1):
            print(f"Error: Task [{name}] cannot run on both cores simultaneously.")
            return False
        
        # Ensure we don't have race conditions by just updating config
        # The runners will pick it up
        self.config[name] = affinity
        print(f"Task [{name}] affinity updated to {affinity}")
        return True

    def _update_tasks(self, core_id):
        """Check config and start/stop tasks for this core."""
        # Iterate over a copy of items to avoid modification issues if any
        # Also, task_classes might be updated? Unlikely.
        # But config values (affinity) might be updated by another thread.
        current_config = list(self.config.items())

        for name, affinity in current_config:
            should_run = (affinity[core_id] == 1)
            # Check if task is already running in THIS core's list
            is_running = name in self.active_tasks[core_id]

            if should_run and not is_running:
                # Instantiate if not exists (Singleton pattern for Task instance)
                if name not in self.tasks:
                    if name in self.task_classes:
                        try:
                            new_task = self.task_classes[name](name, self.ctx)
                            # Apply run_once flag if set
                            run_once = getattr(self, '_run_once_flags', {}).get(name, False)
                            new_task.run_once = run_once
                            self.tasks[name] = new_task
                        except Exception as e:
                            print(f"❌ [Core {core_id}] Failed to instantiate {name}: {e}")
                            continue
                    else:
                        print(f"⚠️ [Core {core_id}] Task class for {name} not found!")
                        continue
                
                task = self.tasks[name]
                
                # Double check affinity to avoid race condition?
                # If user quickly switched (1,0) -> (0,1), both cores might see "should_run" for a brief moment?
                # Core 0 sees (1,0) -> Runs. Core 1 sees (0,1) -> Runs.
                # Ideally we need a lock or atomic flag.
                # But for now, let's assume config changes are slow and infrequent.
                
                print(f"[Core {core_id}] Starting task: {name}")
                try:
                    task.on_start()
                    self.active_tasks[core_id][name] = task
                except Exception as e:
                    print(f"❌ [Core {core_id}] Failed to start {name}: {e}")

            elif not should_run and is_running:
                # Stop and remove
                task = self.active_tasks[core_id][name]
                print(f"[Core {core_id}] Stopping task: {name}")
                try:
                    task.on_stop()
                except Exception as e:
                    print(f"❌ [Core {core_id}] Error stopping {name}: {e}")
                del self.active_tasks[core_id][name]

    def runner_loop(self, core_id):
        print(f"🚀 [Core {core_id}] Task Runner Started")
        
        # Small delay to let system stabilize
        time.sleep_ms(100 if core_id == 0 else 500)
        
        # Performance Counters
        loop_count = 0
        start_time = time.ticks_ms()
        
        # Ensure perf dict exists
        if "perf" not in bus.shared:
            bus.shared["perf"] = {}

        while bus.shared.get("engine_run", True):
            # 1. Update task list based on config
            self._update_tasks(core_id)
            
            # 2. Run active tasks
            if not self.active_tasks[core_id]:
                time.sleep_ms(100) # Idle wait
                continue

            # Run all tasks for this core
            # Copy keys to allow modification during iteration (for one-shot removal)
            current_tasks = list(self.active_tasks[core_id].items())
            
            for name, task in current_tasks:
                try:
                    task.loop()
                    
                    # Handle Run-Once
                    if getattr(task, 'run_once', False):
                        print(f"[Core {core_id}] One-shot task {name} finished. Stopping.")
                        try: task.on_stop()
                        except: pass
                        del self.active_tasks[core_id][name]
                        # Also disable in config to prevent auto-restart?
                        # Or just rely on it being removed from active_tasks?
                        # If we don't update config, _update_tasks will restart it next loop!
                        # So we must update config.
                        self.config[name] = (0, 0)
                        
                except Exception as e:
                    print(f"❌ [Core {core_id}] Task {task.name} Loop Error: {e}")
                    time.sleep_ms(1000) # Prevent tight loop on error

            # 3. Performance Monitoring
            loop_count += 1
            now = time.ticks_ms()
            duration = time.ticks_diff(now, start_time)
            
            if duration >= 2000: # Report every 2 seconds
                # Avoid division by zero
                if loop_count > 0:
                    avg_time_ms = duration / loop_count
                    
                    # Store in shared memory
                    try:
                        bus.shared["perf"][f"core{core_id}_loop_ms"] = avg_time_ms
                        bus.shared["perf"][f"core{core_id}_loops_per_sec"] = (loop_count * 1000) / duration
                    except:
                        bus.shared["perf"] = {
                            f"core{core_id}_loop_ms": avg_time_ms,
                            f"core{core_id}_loops_per_sec": (loop_count * 1000) / duration
                        }
                
                loop_count = 0
                start_time = now

            # 4. System maintenance (Core 0 only usually, or distributed)
            if core_id == 0:
                # gc.collect() is expensive, maybe do it less frequently?
                pass
            
            # Optional: yield time to OS/Watchdog
            # time.sleep_us(10)
            
        print(f"🛑 [Core {core_id}] Runner Stopped")

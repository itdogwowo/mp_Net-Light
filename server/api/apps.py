# server/api/apps.py
from django.apps import AppConfig
import os

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        # 僅在主進程啟動一次後台掃描
        if os.environ.get('RUN_MAIN') == 'true':
            from core.bus_manager import bus_manager
            # bus_manager.start_background_tasks()
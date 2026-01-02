# /action/registry.py
# 統一註冊入口：把各 action 模組掛上去

from action import file_actions
from action import fs_actions

def register_all(app):
    file_actions.register(app)
    fs_actions.register(app)
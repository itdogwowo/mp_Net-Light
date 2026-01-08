# light_control/config_store.py
from __future__ import annotations
import json
from pathlib import Path
from django.conf import settings

CFG_DIR = Path(settings.MEDIA_ROOT) / "netlight" / "config"

def _ensure_dir():
    CFG_DIR.mkdir(parents=True, exist_ok=True)

def load_json(filename, default=None):
    """載入 JSON 文件"""
    file_path = Path(settings.MEDIA_ROOT) / "netlight" / "config" / filename
    
    if not file_path.exists():
        return default if default is not None else {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filename}: {e}")
        return default if default is not None else {}

def save_json(filename, data):
    """保存 JSON 文件"""
    file_path = Path(settings.MEDIA_ROOT) / "netlight" / "config" / filename
    
    # 確保目錄存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return True

def mapping_filename(slave_id: int) -> str:
    return f"mapping_slave_{slave_id}.json"

def load_mapping(slave_id: int):
    """載入指定 slave 的 mapping 文件"""
    file_path = get_mapping_path(slave_id)
    
    if not file_path.exists():
        return None  # 返回 None 表示文件不存在
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 兼容舊版本：如果沒有 ox, oy 字段，添加預設值
        if 'ox' not in data:
            data['ox'] = 0
        if 'oy' not in data:
            data['oy'] = 0
        
        # 確保版本號為 2
        data['version'] = 2
        
        return data
    except Exception as e:
        print(f"Error loading mapping for slave {slave_id}: {e}")
        return None

def save_mapping(slave_id: int, data: dict):
    """保存 mapping 文件"""
    file_path = get_mapping_path(slave_id)
    
    # 確保目錄存在
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return True


def get_mapping_path(slave_id: int) -> Path:
    """獲取 mapping 文件路徑"""
    return Path(settings.MEDIA_ROOT) / "netlight" / "mappings" / f"mapping_slave_{slave_id}.json"
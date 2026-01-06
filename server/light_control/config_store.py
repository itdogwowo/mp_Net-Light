# light_control/config_store.py
from __future__ import annotations
import json
from pathlib import Path
from django.conf import settings

CFG_DIR = Path(settings.MEDIA_ROOT) / "netlight" / "config"

def _ensure_dir():
    CFG_DIR.mkdir(parents=True, exist_ok=True)

def load_json(name: str, default):
    _ensure_dir()
    p = CFG_DIR / name
    if not p.exists():
        return default
    return json.loads(p.read_text("utf-8"))

def save_json(name: str, data):
    _ensure_dir()
    p = CFG_DIR / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

def mapping_filename(slave_id: int) -> str:
    return f"mapping_slave_{slave_id}.json"

def load_mapping(slave_id: int):
    return load_json(mapping_filename(slave_id), default=None)

def save_mapping(slave_id: int, data):
    save_json(mapping_filename(slave_id), data)
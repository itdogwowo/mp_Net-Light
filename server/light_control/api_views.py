# light_control/api_views.py
from __future__ import annotations
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json

from .pxld_v3_decoder import PXLDv3
from .config_store import load_json, save_json, load_mapping, save_mapping

def _pxld_path(name: str) -> Path:
    # 只允許讀 media/netlight/pxld/
    return Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / name

@require_http_methods(["GET"])
def pxld_info(request):
    name = request.GET.get("name", "show.pxld")
    p = _pxld_path(name)
    if not p.exists():
        return JsonResponse({"ok": False, "err": f"PXLD not found: {p}"}, status=404)

    d = PXLDv3(str(p))
    return JsonResponse({"ok": True, "info": d.get_info_dict()})

@require_http_methods(["GET"])
def pxld_slaves(request):
    name = request.GET.get("name", "show.pxld")
    p = _pxld_path(name)
    if not p.exists():
        return JsonResponse({"ok": False, "err": f"PXLD not found: {p}"}, status=404)

    d = PXLDv3(str(p))
    slaves = [s.__dict__ for s in d.get_frame0_slaves()]
    return JsonResponse({"ok": True, "slaves": slaves})

@require_http_methods(["GET"])
def cfg_slaves_get(request):
    data = load_json("slaves.json", default={"version": 1, "slaves": []})
    return JsonResponse({"ok": True, "data": data})

@require_http_methods(["POST"])
def cfg_slaves_set(request):
    body = json.loads(request.body.decode("utf-8"))
    save_json("slaves.json", body)
    return JsonResponse({"ok": True})

@require_http_methods(["GET"])
def cfg_layout_get(request):
    data = load_json("layout.json", default={"version": 1, "layout": []})
    return JsonResponse({"ok": True, "data": data})

@require_http_methods(["POST"])
def cfg_layout_set(request):
    body = json.loads(request.body.decode("utf-8"))
    save_json("layout.json", body)
    return JsonResponse({"ok": True})

@require_http_methods(["GET"])
def mapping_get(request):
    slave_id = int(request.GET.get("slave_id", "-1"))
    if slave_id < 0:
        return JsonResponse({"ok": False, "err": "missing slave_id"}, status=400)

    data = load_mapping(slave_id)
    return JsonResponse({"ok": True, "data": data})

@require_http_methods(["POST"])
def mapping_set(request):
    """
    body:
      {
        "slave_id": 3,
        "version": 1,
        "w": 40,
        "h": 10,
        "map": [{"x":0,"y":0,"pxld_id":0,"mcu_id":12}]
      }
    """
    body = json.loads(request.body.decode("utf-8"))
    slave_id = int(body["slave_id"])
    save_mapping(slave_id, body)
    return JsonResponse({"ok": True})
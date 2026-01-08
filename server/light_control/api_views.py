# light_control/api_views.py
from __future__ import annotations
from pathlib import Path
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import os, json

from .pxld_v3_decoder_api import PXLDv3DecoderAPI
from .pxld_v3_decoder import PXLDv3
from .config_store import load_json, save_json, load_mapping, save_mapping

def _pxld_path(name: str) -> Path:
    # 只允許讀 media/netlight/pxld/
    return Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / name

# 新增：獲取或創建 mapping 的函數
def get_or_create_mapping(slave_id: int, pixel_count: int):
    """
    獲取或創建 mapping 資料
    如果 mapping 文件不存在，則根據 pixel_count 創建預設 mapping
    包含 ox, oy 字段
    """
    data = load_mapping(slave_id)
    
    if data is None:
        # 計算預設的寬高
        w = min(20, max(1, pixel_count))
        h = (pixel_count + w - 1) // w  # 向上取整
        
        # 創建預設的 row-major mapping
        default_map = []
        for y in range(h):
            for x in range(w):
                pxld_id = y * w + x
                if pxld_id < pixel_count:  # 確保不超過 pixel_count
                    default_map.append({
                        "x": x,
                        "y": y,
                        "pxld_id": pxld_id,
                        "mcu_id": pxld_id
                    })
        
        # 創建資料結構，包含 ox, oy
        data = {
            "version": 2,  # 版本 2 包含 ox, oy
            "slave_id": slave_id,
            "w": w,
            "h": h,
            "ox": 0,  # 預設位置 (0, 0)
            "oy": 0,
            "map": default_map
        }
        
        # 保存到文件
        save_mapping(slave_id, data)
    
    return data


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
    print(p)
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
    
    # 獲取 PXLD 檔案中的 pixel_count
    name = request.GET.get("name", "show.pxld")
    pixel_count = 0
    
    try:
        # 讀取 PXLD 檔案獲取 pixel_count
        p = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / name
        if p.exists():
            d = PXLDv3(str(p))
            slaves = d.get_frame0_slaves()
            for slave in slaves:
                if slave.slave_id == slave_id:
                    pixel_count = slave.pixel_count
                    break
    except Exception as e:
        print(f"Error reading PXLD for pixel_count: {e}")
    
    # 使用新的 get_or_create_mapping 函數
    data = get_or_create_mapping(slave_id, pixel_count)
    
    return JsonResponse({"ok": True, "data": data})


@require_http_methods(["GET"])
def mapping_status(request):
    """
    獲取所有 mapping 文件的狀態
    """
    name = request.GET.get("name", "show.pxld")
    status_list = []
    
    try:
        # 讀取 PXLD 獲取 slave 列表
        p = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / name
        if p.exists():
            d = PXLDv3(str(p))
            slaves = d.get_frame0_slaves()
            
            for slave in slaves:
                slave_id = slave.slave_id
                data = load_mapping(slave_id)
                
                status_list.append({
                    "slave_id": slave_id,
                    "pixel_count": slave.pixel_count,
                    "has_mapping": data is not None,
                    "mapping_count": len(data.get("map", [])) if data else 0,
                    "dimensions": {
                        "w": data.get("w", 0) if data else 0,
                        "h": data.get("h", 0) if data else 0
                    }
                })
    
    except Exception as e:
        return JsonResponse({"ok": False, "err": str(e)}, status=500)
    
    return JsonResponse({"ok": True, "status": status_list})


@require_http_methods(["POST"])
def mapping_set(request):
    """
    單個 slave 或批量保存 mapping
    版本 2 格式包含 ox, oy
    """
    body = json.loads(request.body.decode("utf-8"))
    
    # 檢查是否為批量保存
    if body.get("batch") is True:
        # 批量保存多個 slave 的 mapping
        mappings = body.get("mappings", [])
        results = []
        
        for mapping_data in mappings:
            slave_id = int(mapping_data["slave_id"])
            try:
                # 確保每個 mapping 都有 ox, oy
                if 'ox' not in mapping_data:
                    mapping_data['ox'] = 0
                if 'oy' not in mapping_data:
                    mapping_data['oy'] = 0
                
                save_mapping(slave_id, mapping_data)
                results.append({"slave_id": slave_id, "ok": True})
            except Exception as e:
                results.append({"slave_id": slave_id, "ok": False, "err": str(e)})
        
        # 檢查是否有失敗的保存
        failed = [r for r in results if not r["ok"]]
        
        if failed:
            return JsonResponse({
                "ok": False, 
                "err": f"部分保存失敗: {failed}",
                "results": results
            }, status=207)
        
        return JsonResponse({"ok": True, "results": results})
    else:
        # 單個 slave 保存
        slave_id = int(body["slave_id"])
        
        # 確保有 ox, oy 字段
        if 'ox' not in body:
            body['ox'] = 0
        if 'oy' not in body:
            body['oy'] = 0
        
        save_mapping(slave_id, body)
        return JsonResponse({"ok": True})

@require_http_methods(["GET"])
def pxld_slave_frame_rgbw(request):
    """
    GET:
      /light/api/pxld/slave_frame_rgbw?name=show.pxld&frame=0&slave_id=1

    Return:
      {"ok":true, "b64":"...base64...", "frame":0, "slave_id":1}
    """
    name = request.GET.get("name", "show.pxld")
    frame_id = int(request.GET.get("frame", "0"))
    slave_id = int(request.GET.get("slave_id", "-1"))
    if slave_id < 0:
        return JsonResponse({"ok": False, "err": "missing slave_id"}, status=400)

    p = _pxld_path(name)
    if not p.exists():
        return JsonResponse({"ok": False, "err": f"PXLD not found: {p}"}, status=404)

    try:
        dec = PXLDv3DecoderAPI(str(p))
        b64 = dec.get_slave_rgbw_b64(frame_id, slave_id)
        return JsonResponse({"ok": True, "b64": b64, "frame": frame_id, "slave_id": slave_id})
    except Exception as e:
        return JsonResponse({"ok": False, "err": str(e)}, status=400)

# light_control/api_views.py - 新增總畫板 API
@require_http_methods(["GET"])
def pxld_all_slaves_rgbw(request):
    """
    獲取所有 slave 在總畫板中的 RGBW 數據（考慮 mapping）
    GET: /light/api/pxld/all_slaves_rgbw?name=show.pxld&frame=0
    Return: {"ok":true, "data": {slave_id: {ox, oy, w, h, rgbw_base64}}}
    """
    name = request.GET.get("name", "show.pxld")
    frame_id = int(request.GET.get("frame", "0"))
    
    p = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / name
    if not p.exists():
        return JsonResponse({"ok": False, "err": f"PXLD not found: {p}"}, status=404)
    
    try:
        dec = PXLDv3DecoderAPI(str(p))
        d = PXLDv3(str(p))
        
        # 獲取所有 slave 的基本信息
        slaves_info = []
        for s in d.get_frame0_slaves():
            sid = s.slave_id
            pixel_count = s.pixel_count
            
            # 獲取 layout
            layout_file = Path(settings.MEDIA_ROOT) / "netlight" / "mappings" / f"mapping_slave_{sid}.json"
            ox, oy = 0, 0
            if layout_file.exists():
                with open(layout_file, 'r') as f:
                    layout_data = json.load(f)
                    ox = layout_data.get("ox", 0)
                    oy = layout_data.get("oy", 0)
            
            # 獲取 RGBW 數據
            rgbw_b64 = dec.get_slave_rgbw_b64(frame_id, sid)
            
            slaves_info.append({
                "slave_id": sid,
                "ox": ox,
                "oy": oy,
                "pixel_count": pixel_count,
                "rgbw_b64": rgbw_b64
            })
        
        return JsonResponse({"ok": True, "data": slaves_info})
    except Exception as e:
        return JsonResponse({"ok": False, "err": str(e)}, status=400)


@require_http_methods(["GET"])
def layout_get(request):
    """獲取所有 slave 的佈局"""
    data = load_json("layout.json", default={"version": 1, "layout": []})
    return JsonResponse({"ok": True, "data": data})


@require_http_methods(["POST"])
def layout_set(request):
    """設置所有 slave 的佈局"""
    body = json.loads(request.body.decode("utf-8"))
    save_json("layout.json", body)
    return JsonResponse({"ok": True})

def auto_arrange_layout(slaves_data, grid_width=140):
    """
    自動排列 slave 在總畫板中的位置
    避免重疊，確保所有 slave 可見
    """
    layout = {}
    current_x = 0
    current_y = 0
    max_row_height = 0
    
    # 按照 slave_id 排序，確保每次排列順序一致
    sorted_slaves = sorted(slaves_data, key=lambda x: x.slave_id)
    
    for slave in sorted_slaves:
        slave_id = slave.slave_id
        pixel_count = slave.pixel_count
        
        # 計算 slave 的尺寸
        w = min(20, max(1, pixel_count))
        h = (pixel_count + w - 1) // w
        
        # 檢查是否會超出畫布寬度
        if current_x + w > grid_width:
            current_x = 0
            current_y += max_row_height + 2  # 增加間隔
            max_row_height = 0
        
        # 設置位置
        layout[slave_id] = {
            "ox": current_x,
            "oy": current_y,
            "w": w,
            "h": h
        }
        
        # 更新當前位置和最大行高
        current_x += w + 2  # 增加間隔
        max_row_height = max(max_row_height, h)
    
    return layout


@require_http_methods(["GET"])
def auto_arrange(request):
    """自動排列所有 slave 在總畫板中的位置"""
    name = request.GET.get("name", "show.pxld")
    
    p = Path(settings.MEDIA_ROOT) / "netlight" / "pxld" / name
    if not p.exists():
        return JsonResponse({"ok": False, "err": f"PXLD not found: {p}"}, status=404)
    
    try:
        d = PXLDv3(str(p))
        slaves = d.get_frame0_slaves()
        
        # 自動排列
        layout = auto_arrange_layout(slaves)
        
        # 保存到每個 slave 的 mapping 文件
        for slave in slaves:
            slave_id = slave.slave_id
            if slave_id in layout:
                # 載入現有 mapping
                data = load_mapping(slave_id)
                if data is None:
                    # 創建新 mapping
                    data = {
                        "version": 2,
                        "slave_id": slave_id,
                        "w": layout[slave_id]["w"],
                        "h": layout[slave_id]["h"],
                        "ox": layout[slave_id]["ox"],
                        "oy": layout[slave_id]["oy"],
                        "map": []
                    }
                else:
                    # 更新現有 mapping
                    data["ox"] = layout[slave_id]["ox"]
                    data["oy"] = layout[slave_id]["oy"]
                
                # 保存
                save_mapping(slave_id, data)
        
        return JsonResponse({"ok": True, "layout": layout})
    except Exception as e:
        return JsonResponse({"ok": False, "err": str(e)}, status=400)
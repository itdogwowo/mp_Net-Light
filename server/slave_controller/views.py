# slave_controller/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt  # 🔥 新增
import json
from .device_discovery import discovery_service

def device_list_page(request):
    """設備列表頁面"""
    return render(request, 'slave_controller/device_list.html', {
        'title': 'Slave Controller'
    })

def api_device_list(request):
    """API: 獲取設備列表"""
    devices = discovery_service.get_devices()
    return JsonResponse({
        "ok": True,
        "devices": devices,
        "count": len(devices)
    })

# 🔥 新增: 手動觸發發現
@csrf_exempt  # 🔥 豁免 CSRF 檢查
@require_http_methods(["POST"])
def api_discover(request):
    """手動觸發設備發現"""
    result = discovery_service.discover_once()
    return JsonResponse(result)

# 🔥 新增: 連接設備
@csrf_exempt  # 🔥 豁免 CSRF 檢查
@require_http_methods(["POST"])
def api_device_connect(request):
    """指示設備連接 WebSocket"""
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        
        result = discovery_service.connect_device(slave_id)
        return JsonResponse(result)
        
    except Exception as e:
        return JsonResponse({"ok": False, "err": str(e)}, status=500)

# 文件上傳/下載暫時保留
@csrf_exempt  # 🔥 豁免 CSRF 檢查
@require_http_methods(["POST"])
def api_file_upload(request):
    # TODO: 實現通過 WebSocket 上傳
    return JsonResponse({"ok": False, "err": "尚未實現"})

@csrf_exempt  # 🔥 豁免 CSRF 檢查
@require_http_methods(["POST"])
def api_file_download(request):
    # TODO: 實現通過 WebSocket 下載
    return JsonResponse({"ok": False, "err": "尚未實現"})
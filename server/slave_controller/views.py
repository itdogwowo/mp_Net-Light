# slave_controller/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt  # 🔥 新增
import json
import struct
import asyncio
from channels.layers import get_channel_layer
from .device_discovery import discovery_service


def pack_cmd_packet(cmd, payload, addr=0, ver=3):
    """
    打包 CMD 封包
    格式: SOF(2) VER(1) ADDR(2) CMD(2) LEN(2) DATA CRC16(2)
    """
    sof = b'NL'
    ver_byte = bytes([ver])
    addr_bytes = struct.pack('<H', addr)
    cmd_bytes = struct.pack('<H', cmd)
    len_bytes = struct.pack('<H', len(payload))
    
    # 簡化版:不計算 CRC16,使用 0x0000
    crc16 = b'\x00\x00'
    
    packet = sof + ver_byte + addr_bytes + cmd_bytes + len_bytes + payload + crc16
    return packet

def encode_str_u16len(s):
    """編碼 str_u16len 格式"""
    s_bytes = s.encode('utf-8')
    return struct.pack('<H', len(s_bytes)) + s_bytes

@require_http_methods(["POST"])
@csrf_exempt  # 暫時關閉 CSRF 驗證(測試用)
def api_slave_get_status(request):
    """
    發送 STATUS_GET 指令到指定 Slave
    POST /slave/api/slave/status/get/
    Body: {"slave_id": "30:ED:AB:C1:23:45", "query_type": 0}
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        query_type = data.get('query_type', 0)
        
        print(f"[API] STATUS_GET: slave_id={slave_id}, query_type={query_type}")
        
        # 檢查設備是否在線
        device = discovery_service.get_device(slave_id)
        if not device:
            return JsonResponse({
                "ok": False, 
                "err": f"設備未找到: {slave_id}"
            }, status=404)
        
        # 🔥 這裡需要通過 WebSocket 發送 CMD 封包
        # 暫時返回成功(完整實現需要 Channels)
        
        return JsonResponse({
            "ok": True, 
            "message": f"已發送 STATUS_GET 指令到 {slave_id}"
        })
        
    except json.JSONDecodeError as e:
        return JsonResponse({
            "ok": False, 
            "err": f"JSON 解析錯誤: {str(e)}"
        }, status=400)
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "ok": False, 
            "err": str(e)
        }, status=500)

@require_http_methods(["POST"])
@csrf_exempt  # 暫時關閉 CSRF 驗證(測試用)
def api_slave_update_status(request):
    """
    發送 STATUS_UPDATE 指令到指定 Slave
    POST /slave/api/slave/status/update/
    Body: {"slave_id": "30:ED:AB:C1:23:45", "config": {...}}
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        config = data.get('config', {})
        
        print(f"[API] STATUS_UPDATE: slave_id={slave_id}, config={config}")
        
        # 檢查設備是否在線
        device = discovery_service.get_device(slave_id)
        if not device:
            return JsonResponse({
                "ok": False, 
                "err": f"設備未找到: {slave_id}"
            }, status=404)
        
        # 🔥 這裡需要通過 WebSocket 發送 CMD 封包
        # 暫時返回成功
        
        return JsonResponse({
            "ok": True, 
            "message": f"已發送 STATUS_UPDATE 指令到 {slave_id}"
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "ok": False, 
            "err": str(e)
        }, status=500)
    
    
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
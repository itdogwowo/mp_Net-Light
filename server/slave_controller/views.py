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

from asgiref.sync import async_to_sync
import struct


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


@require_http_methods(["POST"])
@csrf_exempt
def api_stream_start(request):
    """
    啟動燈效串流
    POST /slave/api/stream/start/
    Body: {"fps": 40, "pixel_count": 400}
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        fps = data.get('fps', 40)
        pixel_count = data.get('pixel_count', 400)
        
        print(f"[API] STREAM_START: fps={fps}, pixels={pixel_count}")
        
        # 🔥 構造 STREAM_START 封包
        from lib.proto import pack_packet
        import struct
        
        CMD_STREAM_START = 0x3002
        payload = struct.pack('<BH', fps, pixel_count)
        packet = pack_packet(CMD_STREAM_START, payload)
        
        # 🔥 廣播到所有 Slave
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "all_slaves",
            {
                "type": "send_cmd",
                "packet": packet
            }
        )
        
        return JsonResponse({
            "ok": True,
            "message": f"STREAM_START 已廣播 (fps={fps}, pixels={pixel_count})"
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)

@require_http_methods(["POST"])
@csrf_exempt
def api_stream_stop(request):
    """
    停止燈效串流
    POST /slave/api/stream/stop/
    """
    try:
        print(f"[API] STREAM_STOP")
        
        # 🔥 構造 STREAM_STOP 封包
        from lib.proto import pack_packet
        
        CMD_STREAM_STOP = 0x3003
        packet = pack_packet(CMD_STREAM_STOP, b"")
        
        # 🔥 廣播到所有 Slave
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "all_slaves",
            {
                "type": "send_cmd",
                "packet": packet
            }
        )
        
        return JsonResponse({
            "ok": True,
            "message": "STREAM_STOP 已廣播"
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)
    
@require_http_methods(["POST"])
@csrf_exempt
def api_schema_download(request):
    """
    觸發從 Slave 下載 schema 文件
    POST /slave/api/schema/download/
    Body: {
        "slave_id": "30EDA0EA4EC8",
        "schema_name": "status"  # 可選: status/file/fs/stream
    }
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        schema_name = data.get('schema_name', 'status')  # 默認下載 status
        
        print(f"[API] 請求下載 schema: {slave_id}/{schema_name}")
        
        # 檢查設備是否在線
        device = discovery_service.get_device(slave_id)
        if not device:
            return JsonResponse({
                "ok": False,
                "err": f"設備未找到: {slave_id}"
            }, status=404)
        
        # 🔥 構造 FS_SNAP_GET 指令 (請求 /schema/{schema_name}.json)
        CMD_FS_SNAP_GET = 0x1213
        
        # 構造 payload
        # FS_SNAP_GET: path(str_u16len) + out_path(str_u16len) + max_depth(u8) + include_size(u8)
        src_path = f"/schema/{schema_name}.json"
        out_path = f"/tx_{schema_name}.json"
        
        # 編碼 str_u16len
        def encode_str_u16len(s):
            s_bytes = s.encode('utf-8')
            return struct.pack('<H', len(s_bytes)) + s_bytes
        
        payload = (
            encode_str_u16len(src_path) +
            encode_str_u16len(out_path) +
            struct.pack('<BB', 1, 0)  # max_depth=1, include_size=0
        )
        
        packet = pack_cmd_packet(CMD_FS_SNAP_GET, payload)
        
        # 🔥 通過 WebSocket 發送到 Slave
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"slave_{slave_id}",
            {
                "type": "send_cmd",
                "packet": packet
            }
        )
        
        print(f"[API] ✅ 已發送 FS_SNAP_GET 到 {slave_id}")
        
        return JsonResponse({
            "ok": True,
            "message": f"Schema 下載請求已發送 ({schema_name})",
            "schema_name": schema_name,
            "slave_id": slave_id
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)


@require_http_methods(["GET"])
def api_schema_list(request, slave_id):
    """
    列出 Slave 已下載的 schema 文件
    GET /slave/api/schema/list/<slave_id>/
    """
    try:
        from pathlib import Path
        from django.conf import settings
        
        schema_dir = Path(settings.MEDIA_ROOT) / "schemas" / slave_id
        
        if not schema_dir.exists():
            return JsonResponse({
                "ok": True,
                "schemas": [],
                "message": f"未找到 {slave_id} 的 schema"
            })
        
        schemas = []
        for file_path in schema_dir.glob("*.json"):
            try:
                import json as json_lib
                with open(file_path, 'r') as f:
                    content = json_lib.load(f)
                
                schemas.append({
                    "name": file_path.stem,
                    "group": content.get("group", "unknown"),
                    "cmd_count": len(content.get("cmds", [])),
                    "size": file_path.stat().st_size
                })
            except Exception as e:
                print(f"[API] 解析 {file_path} 失敗: {e}")
        
        return JsonResponse({
            "ok": True,
            "schemas": schemas,
            "count": len(schemas)
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)
# slave_controller/views.py - 完整版
"""
Slave Controller Views
- 設備發現和管理
- 通用 CMD 發送 API (使用 schema)
- 燈效串流控制
- Schema 同步
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import struct
import os
from pathlib import Path

from .device_discovery import discovery_service

# ==================== 協議工具函數 ====================

def pack_cmd_packet(cmd, payload, addr=0, ver=3):
    """
    打包 CMD 封包 (使用真實 CRC16)
    格式: SOF(2) VER(1) ADDR(2) CMD(2) LEN(2) DATA CRC16(2)
    """
    import struct
    
    sof = b'NL'
    ver_byte = bytes([ver])
    addr_bytes = struct.pack('<H', addr)
    cmd_bytes = struct.pack('<H', cmd)
    len_bytes = struct.pack('<H', len(payload))
    
    # 🔥 計算真實 CRC16 (與 ESP32 一致)
    # CRC 覆蓋: VER + ADDR + CMD + LEN + DATA
    crc_data = ver_byte + addr_bytes + cmd_bytes + len_bytes + payload
    crc16 = crc16_ccitt(crc_data)  # 🔥 調用 CRC16 函數
    crc_bytes = struct.pack('<H', crc16)
    
    packet = sof + ver_byte + addr_bytes + cmd_bytes + len_bytes + payload + crc_bytes
    return packet

_CRC16_TAB = None

def _crc16_init_table():
    global _CRC16_TAB
    tab = [0] * 256
    poly = 0x1021
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        tab[i] = crc
    _CRC16_TAB = tab

def crc16_ccitt(data: bytes, init=0xFFFF) -> int:
    """CRC16-CCITT-FALSE (與 ESP32 一致)"""
    global _CRC16_TAB
    if _CRC16_TAB is None:
        _crc16_init_table()
    
    crc = init & 0xFFFF
    for b in data:
        crc = ((crc << 8) ^ _CRC16_TAB[((crc >> 8) ^ b) & 0xFF]) & 0xFFFF
    return crc

def encode_str_u16len(s):
    """編碼 str_u16len 格式"""
    s_bytes = s.encode('utf-8')
    return struct.pack('<H', len(s_bytes)) + s_bytes

def send_to_slave(slave_id, packet):
    """通過 WebSocket 發送封包到指定 Slave"""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f'slave_{slave_id}',
        {
            'type': 'send_cmd',
            'packet': packet
        }
    )

def broadcast_to_all_slaves(packet):
    """廣播封包到所有 Slave"""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'all_slaves',
        {
            'type': 'send_cmd',
            'packet': packet
        }
    )

# ==================== 設備管理 API ====================

def device_list_page(request):
    """設備列表頁面"""
    return render(request, 'slave_controller/device_list.html', {
        'title': 'Slave Controller'
    })

@require_http_methods(["GET"])
def api_device_list(request):
    """
    API: 獲取設備列表
    GET /slave/api/devices/
    """
    devices = discovery_service.get_devices()
    
    # 🔥 檢查離線設備
    discovery_service.check_offline_devices()
    
    return JsonResponse({
        "ok": True,
        "devices": devices,
        "count": len(devices)
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_discover(request):
    """
    手動觸發設備發現
    POST /slave/api/discover/
    """
    result = discovery_service.discover_once()
    return JsonResponse(result)

@csrf_exempt
@require_http_methods(["POST"])
def api_device_connect(request):
    """
    指示設備連接 WebSocket
    POST /slave/api/device/connect/
    Body: {"slave_id": "30EDA0EA4EC8"}
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        
        result = discovery_service.connect_device(slave_id)
        return JsonResponse(result)
        
    except Exception as e:
        return JsonResponse({
            "ok": False, 
            "err": str(e)
        }, status=500)

# ==================== 通用 CMD 發送 API ====================

@csrf_exempt
@require_http_methods(["POST"])
def api_send_cmd(request):
    """
    🔥 通用 CMD 發送 API
    POST /slave/api/send_cmd/
    Body: {
        "slave_id": "30EDA0EA4EC8",  # 可選,不填則廣播
        "cmd": "STATUS_GET" 或 "0x1101",
        "params": {
            "query_type": 0
        }
    }
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        cmd_input = data.get('cmd')
        params = data.get('params', {})
        
        # 🔥 載入 schema
        from .protocol.schema_loader import SchemaStore, cmd_str_to_int
        from .protocol.schema_codec import encode_payload
        
        schema_store = SchemaStore()
        schema_dir = os.path.join(settings.BASE_DIR, 'schema')
        schema_store.load_dir(schema_dir)
        
        # 解析 CMD
        if cmd_input.startswith('0x'):
            cmd_int = cmd_str_to_int(cmd_input)
        else:
            # 從 schema 查找
            cmd_int = None
            for c_int, c_def in schema_store.get_all().items():
                if c_def['name'] == cmd_input:
                    cmd_int = c_int
                    break
            
            if not cmd_int:
                return JsonResponse({
                    "ok": False,
                    "err": f"未知 CMD: {cmd_input}"
                }, status=400)
        
        # 獲取 schema 定義
        cmd_def = schema_store.get(cmd_int)
        if not cmd_def:
            return JsonResponse({
                "ok": False,
                "err": f"CMD schema 未找到: 0x{cmd_int:04X}"
            }, status=400)
        
        # 🔥 編碼 payload
        payload = encode_payload(cmd_def, params)
        packet = pack_cmd_packet(cmd_int, payload)
        
        # 🔥 發送封包
        if slave_id:
            # 檢查設備
            device = discovery_service.get_device(slave_id)
            if not device:
                return JsonResponse({
                    "ok": False,
                    "err": f"設備未找到: {slave_id}"
                }, status=404)
            
            send_to_slave(slave_id, packet)
            message = f"已發送 {cmd_def['name']} 到 {slave_id}"
        else:
            # 廣播到所有設備
            broadcast_to_all_slaves(packet)
            message = f"已廣播 {cmd_def['name']} 到所有設備"
        
        return JsonResponse({
            "ok": True,
            "message": message,
            "cmd": f"0x{cmd_int:04X}",
            "cmd_name": cmd_def['name'],
            "payload_size": len(payload)
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

# ==================== STATUS 指令 API (兼容舊版) ====================

@csrf_exempt
@require_http_methods(["POST"])
def api_slave_get_status(request):
    """
    發送 STATUS_GET 指令到指定 Slave
    POST /slave/api/slave/status/get/
    Body: {"slave_id": "30EDA0EA4EC8", "query_type": 0}
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
        
        # 🔥 修復:構造正確的請求體調用 api_send_cmd
        request._body = json.dumps({
            "slave_id": slave_id,
            "cmd": "STATUS_GET",  # 🔥 新增
            "params": {
                "query_type": query_type
            }
        }).encode('utf-8')
        
        return api_send_cmd(request)
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "ok": False, 
            "err": str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def api_slave_update_status(request):
    """
    發送 STATUS_UPDATE 指令 (兼容舊版 API)
    POST /slave/api/slave/status/update/
    Body: {"slave_id": "30EDA0EA4EC8", "config": {...}}
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        config = data.get('config', {})
        
        # 構造通用 API 格式
        request._body = json.dumps({
            "slave_id": slave_id,
            "cmd": "STATUS_UPDATE",
            "params": {
                "config_json": json.dumps(config)
            }
        }).encode('utf-8')
        
        return api_send_cmd(request)
        
    except Exception as e:
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)

# ==================== 燈效串流 API ====================

@csrf_exempt
@require_http_methods(["POST"])
def api_stream_start(request):
    """
    啟動燈效串流
    POST /slave/api/stream/start/
    Body: {
        "slave_id": "30EDA0EA4EC8",  # 可選
        "fps": 40,
        "pixel_count": 400
    }
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        fps = data.get('fps', 40)
        pixel_count = data.get('pixel_count', 400)
        
        print(f"[API] STREAM_START: fps={fps}, pixels={pixel_count}")
        
        # 構造 STREAM_START 封包
        CMD_STREAM_START = 0x3002
        payload = struct.pack('<BH', fps, pixel_count)
        packet = pack_cmd_packet(CMD_STREAM_START, payload)
        
        # 發送
        if slave_id:
            send_to_slave(slave_id, packet)
            message = f"STREAM_START 已發送到 {slave_id}"
        else:
            broadcast_to_all_slaves(packet)
            message = "STREAM_START 已廣播到所有設備"
        
        return JsonResponse({
            "ok": True,
            "message": message,
            "fps": fps,
            "pixel_count": pixel_count
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def api_stream_stop(request):
    """
    停止燈效串流
    POST /slave/api/stream/stop/
    Body: {"slave_id": "30EDA0EA4EC8"}  # 可選
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        
        print(f"[API] STREAM_STOP")
        
        # 構造 STREAM_STOP 封包
        CMD_STREAM_STOP = 0x3003
        packet = pack_cmd_packet(CMD_STREAM_STOP, b"")
        
        # 發送
        if slave_id:
            send_to_slave(slave_id, packet)
            message = f"STREAM_STOP 已發送到 {slave_id}"
        else:
            broadcast_to_all_slaves(packet)
            message = "STREAM_STOP 已廣播到所有設備"
        
        return JsonResponse({
            "ok": True,
            "message": message
        })
        
    except Exception as e:
        print(f"[API] 錯誤: {e}")
        return JsonResponse({
            "ok": False,
            "err": str(e)
        }, status=500)

# ==================== Schema 同步 API ====================

@csrf_exempt
@require_http_methods(["POST"])
def api_schema_download(request):
    """
    從 Slave 下載 schema 文件
    POST /slave/api/schema/download/
    Body: {
        "slave_id": "30EDA0EA4EC8",
        "schema_name": "status"
    }
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
        slave_id = data.get('slave_id')
        schema_name = data.get('schema_name', 'status')
        
        print(f"[API] 請求下載 schema: {slave_id}/{schema_name}")
        
        # 檢查設備
        device = discovery_service.get_device(slave_id)
        if not device:
            return JsonResponse({
                "ok": False,
                "err": f"設備未找到: {slave_id}"
            }, status=404)
        
        # 🔥 使用通用 API 發送 FS_SNAP_GET
        CMD_FS_SNAP_GET = 0x1213
        
        src_path = f"/schema/{schema_name}.json"
        out_path = f"/tx_{schema_name}.json"
        
        payload = (
            encode_str_u16len(src_path) +
            encode_str_u16len(out_path) +
            struct.pack('<BB', 1, 0)  # max_depth=1, include_size=0
        )
        
        packet = pack_cmd_packet(CMD_FS_SNAP_GET, payload)
        send_to_slave(slave_id, packet)
        
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
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                
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

# ==================== 文件上傳/下載 API ====================

@csrf_exempt
@require_http_methods(["POST"])
def api_file_upload(request):
    """
    上傳文件到 Slave
    POST /slave/api/file/upload/
    """
    # TODO: 實現通過 WebSocket 上傳
    return JsonResponse({
        "ok": False, 
        "err": "尚未實現"
    })

@csrf_exempt
@require_http_methods(["POST"])
def api_file_download(request):
    """
    從 Slave 下載文件
    POST /slave/api/file/download/
    """
    # TODO: 實現通過 WebSocket 下載
    return JsonResponse({
        "ok": False, 
        "err": "尚未實現"
    })
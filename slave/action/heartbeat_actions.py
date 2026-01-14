# /action/heartbeat_actions.py
"""
心跳指令處理
- HEARTBEAT: 發送心跳到 Server
- HEARTBEAT_ACK: 接收 Server 確認
"""

def register(app):
    """註冊心跳指令"""
    from lib.schema_loader import cmd_str_to_int
    
    CMD_HEARTBEAT_ACK = cmd_str_to_int("0x1202")
    
    def on_heartbeat_ack(ctx, args):
        """處理 Server 的心跳確認"""
        server_time = args.get("server_time", 0)
        success = args.get("success", 0)
        
        if success:
            print("[Heartbeat] ✅ Server 確認收到心跳 (server_time={})".format(server_time))
        else:
            print("[Heartbeat] ⚠️ Server 心跳確認失敗")
    
    app.disp.on(CMD_HEARTBEAT_ACK, on_heartbeat_ack)
    print("[Heartbeat] 心跳指令已註冊")
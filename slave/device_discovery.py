# slave_controller/device_discovery.py (簡化版)
def discover_once(self):
    """手動觸發一次設備發現"""
    if not self.broadcast_addr:
        return {"ok": False, "err": "網絡配置未初始化"}
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        try:
            sock.bind((self.local_ip, 0))
        except:
            sock.bind(('0.0.0.0', 0))
        
        message = json.dumps({
            "cmd": "DISCOVER",
            "server_ip": self.local_ip,
            # 🔥 關鍵:直接給 WebSocket URL
            "ws_url": f"ws://{self.local_ip}:8001/ws/slave/",  
            "timestamp": datetime.now().isoformat()
        })
        
        sock.sendto(
            message.encode('utf-8'),
            (self.broadcast_addr, self.broadcast_port)
        )
        
        sock.close()
        
        print(f"[Discovery] 📡 已發送發現廣播")
        return {"ok": True, "message": "發現廣播已發送"}
        
    except Exception as e:
        return {"ok": False, "err": str(e)}
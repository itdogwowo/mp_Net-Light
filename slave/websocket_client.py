# websocket_client.py (修改)
class WebSocketClient:
    def __init__(self, app):
        self.ws = None
        self.connected = False
        self.url = None
        self.app = app  # 🔥 新增:引用 app (包含 dispatcher)
    
    def poll(self):
        """輪詢處理"""
        if not self.connected or not self.ws:
            return
        
        try:
            data = self.ws.recv()
            if data:
                if isinstance(data, bytes):
                    # 🔥 關鍵:收到二進位數據,交給 CMD 解析
                    self._handle_cmd_packet(data)
                elif isinstance(data, str):
                    # JSON 格式(用於測試)
                    self._handle_json_message(json.loads(data))
        except OSError:
            pass
    
    def _handle_cmd_packet(self, packet):
        """
        處理 CMD 二進位封包
        直接交給您的 StreamParser
        """
        # 🔥 使用您現有的 proto.py
        from lib.proto import StreamParser
        
        if not hasattr(self, 'parser'):
            self.parser = StreamParser(max_len=8192)
        
        # feed 數據
        self.parser.feed(packet)
        
        # 解析封包
        while True:
            pkt = self.parser.pop()
            if pkt is None:
                break
            
            # 🔥 交給 dispatcher 處理
            ctx = {
                "transport": "websocket",
                "send": self._send_cmd_response
            }
            self.app.disp.dispatch(pkt.cmd, pkt.payload, ctx)
    
    def _send_cmd_response(self, response_packet):
        """發送 CMD 回應"""
        if self.connected and self.ws:
            self.ws.send(response_packet)  # 發送二進位
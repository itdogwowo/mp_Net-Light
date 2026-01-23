import json
import asyncio # 使用 Python 內建非同步庫，就像 MicroPython 的 uasyncio
from channels.generic.websocket import AsyncWebsocketConsumer


class APIConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        await self.send(text_data=json.dumps({
            'message': message
        }))
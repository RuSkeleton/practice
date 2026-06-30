from fastapi import WebSocket, WebSocketDisconnect, APIRouter
import json
from typing import List, Dict

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.screen_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, screen_code: str = None):
        await websocket.accept()
        self.active_connections.append(websocket)
        if screen_code:
            self.screen_connections[screen_code] = websocket
        print(f"WebSocket подключен. Всего соединений: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        for code, ws in list(self.screen_connections.items()):
            if ws == websocket:
                del self.screen_connections[code]
                break
        print(f"WebSocket отключен. Осталось соединений: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        data = json.dumps(message)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
            except:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

@router.websocket("/ws/slides")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await manager.connect(websocket)
        
        data = await websocket.receive_text()
        try:
            msg = json.loads(data)
            if msg.get("type") == "register":
                screen_code = msg.get("code")
                if screen_code:
                    manager.screen_connections[screen_code] = websocket
                    print(f"Экран {screen_code} зарегистрирован")
        except:
            pass
        
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                manager.disconnect(websocket)
                break
            except Exception as e:
                print(f"WebSocket error: {e}")
                manager.disconnect(websocket)
                break
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket exception: {e}")
        manager.disconnect(websocket)

async def notify_clients(message: dict):
    await manager.broadcast(message)
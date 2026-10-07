import asyncio

from fastapi import WebSocket


class ConnectionManager:
    """Quản lý các kết nối WebSocket đang mở. Một user có thể mở nhiều tab."""

    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = {}  # user_id -> các kết nối
        self.names: dict[str, str] = {}  # user_id -> username

    def connect(self, user_id: str, username: str, ws: WebSocket) -> bool:
        """Trả về True nếu đây là kết nối đầu tiên của user (vừa chuyển sang online)."""
        first = user_id not in self.sockets
        self.sockets.setdefault(user_id, set()).add(ws)
        self.names[user_id] = username
        return first

    def disconnect(self, user_id: str, ws: WebSocket) -> bool:
        """Trả về True nếu user không còn kết nối nào (vừa chuyển sang offline)."""
        conns = self.sockets.get(user_id)
        if conns is None:
            return False
        conns.discard(ws)
        if conns:
            return False
        del self.sockets[user_id]
        return True

    def online_usernames(self) -> list[str]:
        return sorted(self.names[uid] for uid in self.sockets)

    async def _send(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_json(payload)
        except Exception:
            pass  # kết nối hỏng sẽ được dọn ở khối finally của endpoint

    async def send_to_users(self, user_ids, payload: dict) -> None:
        targets = [ws for uid in user_ids for ws in self.sockets.get(str(uid), ())]
        await asyncio.gather(*(self._send(ws, payload) for ws in targets))

    async def broadcast(self, payload: dict) -> None:
        targets = [ws for conns in self.sockets.values() for ws in conns]
        await asyncio.gather(*(self._send(ws, payload) for ws in targets))


manager = ConnectionManager()

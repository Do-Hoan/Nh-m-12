import asyncio

from fastapi import WebSocket


class ConnectionManager:
    """Quản lý các kết nối WebSocket đang mở.

    Hai bảng chính:
      - sockets: user_id -> {các WebSocket}   (một user có thể mở nhiều tab/thiết bị)
      - rooms:   room_id -> {user_id thành viên} (để gửi tin tới cả phòng mà không phải đọc DB mỗi lần)
    """

    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = {}
        self.names: dict[str, str] = {}  # user_id -> username
        self.rooms: dict[str, set[str]] = {}

    # ---------- kết nối theo user ----------
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

    def is_online(self, user_id: str) -> bool:
        return user_id in self.sockets

    def online_user_ids(self) -> list[str]:
        return sorted(self.sockets)

    # ---------- phòng ----------
    def set_room_members(self, room_id: str, user_ids) -> None:
        self.rooms[room_id] = {str(u) for u in user_ids}

    def drop_room(self, room_id: str) -> None:
        self.rooms.pop(room_id, None)

    # ---------- gửi ----------
    async def _send(self, ws: WebSocket, payload: dict) -> None:
        try:
            await ws.send_json(payload)
        except Exception:
            pass  # kết nối hỏng sẽ được dọn ở khối finally của endpoint

    async def send_to_ws(self, ws: WebSocket, payload: dict) -> None:
        await self._send(ws, payload)

    async def send_to_users(self, user_ids, payload: dict) -> None:
        targets = [ws for uid in user_ids for ws in self.sockets.get(str(uid), ())]
        await asyncio.gather(*(self._send(ws, payload) for ws in targets))

    async def send_to_user(self, user_id: str, payload: dict) -> None:
        await self.send_to_users([user_id], payload)

    async def send_to_room(self, room_id: str, payload: dict) -> None:
        await self.send_to_users(self.rooms.get(room_id, ()), payload)

    async def broadcast(self, payload: dict) -> None:
        targets = [ws for conns in self.sockets.values() for ws in conns]
        await asyncio.gather(*(self._send(ws, payload) for ws in targets))


manager = ConnectionManager()

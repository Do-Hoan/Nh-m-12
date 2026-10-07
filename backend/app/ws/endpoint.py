import json

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config import MAX_MESSAGE_LEN
from ..db import db, now
from ..security import decode_token, to_oid
from ..serializers import message_out
from .manager import manager

router = APIRouter()


async def send_error(ws: WebSocket, code: str, detail: str) -> None:
    await ws.send_json({"type": "error", "code": code, "detail": detail})


async def on_message_send(user: dict, ws: WebSocket, data: dict) -> None:
    content = str(data.get("content", "")).strip()
    if not content or len(content) > MAX_MESSAGE_LEN:
        return await send_error(ws, "INVALID_CONTENT", f"Nội dung phải từ 1 đến {MAX_MESSAGE_LEN} ký tự")

    room_oid = to_oid(data.get("room_id"))
    # Kiểm tra quyền: user phải là thành viên của phòng
    room = await db.rooms.find_one({"_id": room_oid, "members": user["_id"]}) if room_oid else None
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    msg = {
        "room_id": room["_id"],
        "sender_id": user["_id"],
        "sender_name": user["username"],
        "content": content,
        "created_at": now(),
    }
    await db.messages.insert_one(msg)  # lưu DB trước, rồi mới phát cho mọi người
    payload = {"type": "message.new", **message_out(msg), "client_id": data.get("client_id")}
    await manager.send_to_users(room["members"], payload)


async def handle_event(user: dict, ws: WebSocket, raw: str) -> None:
    try:
        data = json.loads(raw)
        event_type = data["type"]
    except (ValueError, KeyError, TypeError):
        return await send_error(ws, "BAD_REQUEST", "Tin nhắn phải là JSON có trường 'type'")

    if event_type == "message.send":
        await on_message_send(user, ws, data)
    else:
        await send_error(ws, "UNKNOWN_TYPE", f"Không hỗ trợ sự kiện '{event_type}'")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query("")):
    await ws.accept()

    # Trình duyệt không gắn được header tùy ý khi mở WebSocket -> nhận token qua query
    payload = decode_token(token)
    oid = to_oid(payload["sub"]) if payload else None
    user = await db.users.find_one({"_id": oid}) if oid else None
    if not user:
        await ws.close(code=4401)  # 4401: mã đóng tùy chỉnh = chưa xác thực
        return

    uid, username = str(user["_id"]), user["username"]
    became_online = manager.connect(uid, username, ws)
    await ws.send_json({"type": "presence.list", "users": manager.online_usernames()})
    if became_online:
        await manager.broadcast({"type": "presence.update", "username": username, "status": "online"})

    try:
        while True:
            raw = await ws.receive_text()
            await handle_event(user, ws, raw)
    except WebSocketDisconnect:
        pass
    finally:
        if manager.disconnect(uid, ws):
            await manager.broadcast({"type": "presence.update", "username": username, "status": "offline"})

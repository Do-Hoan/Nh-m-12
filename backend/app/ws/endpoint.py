"""Endpoint WebSocket duy nhất /ws: xác thực JWT, presence, nhận tin nhắn, signaling cuộc gọi.

Giao thức chi tiết: docs/protocol.md
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config import MAX_MESSAGE_LEN, WS_IDLE_TIMEOUT
from ..db import db, now
from ..deps import user_from_token
from ..models import message_out, user_out
from ..security import to_oid
from ..services.storage import is_allowed_image_url
from .calls import calls
from .manager import manager

log = logging.getLogger(__name__)
router = APIRouter()

MAX_FRAME_CHARS = 128 * 1024

# Danh sách emoji được phép sử dụng
ALLOWED_REACTIONS = {
    "❤️",
    "😂",
    "👍",
    "👎",
    "😍",
    "😢",
    "😮",
    "🙏",
    "🔥",
    "👏",
}


async def send_error(ws: WebSocket, code: str, detail: str) -> None:
    await ws.send_json({"type": "error", "code": code, "detail": detail})


async def find_room_of(user: dict, room_id) -> dict | None:
    """Trả về phòng nếu user là thành viên, ngược lại None (dùng cho mọi thao tác theo phòng)."""
    oid = to_oid(room_id)
    return await db.rooms.find_one({"_id": oid, "members": user["_id"]}) if oid else None


# ---------- Tin nhắn ----------
async def on_message_send(user: dict, ws: WebSocket, data: dict) -> None:
    msg_type = data.get("msg_type", "text")
    content = str(data.get("content", "")).strip()
    if msg_type not in ("text", "image"):
        return await send_error(ws, "INVALID_CONTENT", "msg_type phải là 'text' hoặc 'image'")
    if not content or len(content) > MAX_MESSAGE_LEN:
        return await send_error(ws, "INVALID_CONTENT", f"Nội dung phải từ 1 đến {MAX_MESSAGE_LEN} ký tự")
    if msg_type == "image" and not is_allowed_image_url(content):
        return await send_error(ws, "INVALID_CONTENT", "URL ảnh không hợp lệ")

    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    msg = {
        "room_id": room["_id"],
        "sender_id": user["_id"],
        "sender_name": user["username"],
        "type": msg_type,
        "content": content,
        "created_at": now(),
        "read_by": [user["_id"]],
    }
    await db.messages.insert_one(msg)
    manager.set_room_members(str(room["_id"]), room["members"])
    payload = {"type": "message.new", **message_out(msg), "client_id": data.get("client_id")}
    await manager.send_to_room(str(room["_id"]), payload)


async def on_typing(user: dict, ws: WebSocket, data: dict) -> None:
    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    event_type = data.get("type")
    payload = {
        "type": event_type,
        "room_id": str(room["_id"]),
        "user_id": str(user["_id"]),
        "username": user["username"],
    }
    await manager.send_to_room(str(room["_id"]), payload)


async def on_message_read(user: dict, ws: WebSocket, data: dict) -> None:
    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    message_id = data.get("message_id")
    if message_id:
        msg = await db.messages.find_one({"_id": to_oid(message_id), "room_id": room["_id"]})
        if not msg:
            return await send_error(ws, "NOT_FOUND", "Tin nhắn không tồn tại")
    else:
        msg = None

    now_ts = now()
    await db.rooms.update_one({"_id": room["_id"]}, {"$set": {f"read_by.{str(user['_id'])}": now_ts}}, upsert=True)
    if msg:
        await db.messages.update_one({"_id": msg["_id"]}, {"$addToSet": {"read_by": user["_id"]}})

    payload = {"type": "message.read", "room_id": str(room["_id"]), "user_id": str(user["_id"]), "read_at": now_ts.isoformat()}
    if msg:
        payload["message_id"] = str(msg["_id"])
    await manager.send_to_room(str(room["_id"]), payload)


async def on_message_edit(user: dict, ws: WebSocket, data: dict) -> None:
    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    msg = await db.messages.find_one({"_id": to_oid(data.get("message_id")), "room_id": room["_id"]})
    if not msg:
        return await send_error(ws, "NOT_FOUND", "Tin nhắn không tồn tại")
    if str(msg["sender_id"]) != str(user["_id"]):
        return await send_error(ws, "FORBIDDEN", "Bạn không có quyền chỉnh sửa tin nhắn này")

    if msg.get("deleted_at"):
        return await send_error(ws, "NOT_FOUND", "Tin nhắn đã bị thu hồi")
    if msg.get("type", "text") != "text":
        return await send_error(ws, "INVALID_CONTENT", "Chỉ có thể chỉnh sửa tin nhắn văn bản")

    content = str(data.get("content", "")).strip()
    if not content or len(content) > MAX_MESSAGE_LEN:
        return await send_error(ws, "INVALID_CONTENT", f"Nội dung phải từ 1 đến {MAX_MESSAGE_LEN} ký tự")

    updated_at = now()
    result = await db.messages.find_one_and_update(
        {"_id": msg["_id"]},
        {"$set": {"content": content, "edited_at": updated_at}},
        return_document=True,
    )
    payload = {"type": "message.edited", "id": str(result["_id"]), "room_id": str(room["_id"]), "content": content, "edited_at": updated_at.isoformat()}
    await manager.send_to_room(str(room["_id"]), payload)


async def on_message_delete(user: dict, ws: WebSocket, data: dict) -> None:
    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    msg = await db.messages.find_one({"_id": to_oid(data.get("message_id")), "room_id": room["_id"]})
    if not msg:
        return await send_error(ws, "NOT_FOUND", "Tin nhắn không tồn tại")
    if str(msg["sender_id"]) != str(user["_id"]):
        return await send_error(ws, "FORBIDDEN", "Bạn không có quyền thu hồi tin nhắn này")

    deleted_at = now()
    await db.messages.update_one({"_id": msg["_id"]}, {"$set": {"deleted_at": deleted_at, "content": "[tin nhắn đã thu hồi]"}})
    updated = await db.messages.find_one({"_id": msg["_id"]})
    payload = {"type": "message.deleted", "message_id": str(msg["_id"]), "room_id": str(room["_id"]), **message_out(updated)}
    await manager.send_to_room(str(room["_id"]), payload)


async def on_message_reaction(user: dict, ws: WebSocket, data: dict) -> None:
    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")

    emoji = str(data.get("emoji", "")).strip()
    if emoji not in ALLOWED_REACTIONS:
        return await send_error(ws, "INVALID_CONTENT", "Emoji không hợp lệ")

    msg = await db.messages.find_one({"_id": to_oid(data.get("message_id")), "room_id": room["_id"]})
    if not msg:
        return await send_error(ws, "NOT_FOUND", "Tin nhắn không tồn tại")

    if msg.get("deleted_at"):
        return await send_error(ws, "NOT_FOUND", "Tin nhắn đã bị thu hồi")

    reactions = dict(msg.get("reactions") or {})
    users = list(reactions.get(emoji, []))
    uid = user["_id"]

    if uid in users:
        users.remove(uid)
        if not users:
            reactions.pop(emoji, None)
        else:
            reactions[emoji] = users
    else:
        users.append(uid)
        reactions[emoji] = users

    await db.messages.update_one({"_id": msg["_id"]}, {"$set": {"reactions": reactions}})
    updated = await db.messages.find_one({"_id": msg["_id"]})
    payload = {"type": "message.reaction", "message_id": str(msg["_id"]), "room_id": str(room["_id"]), "emoji": emoji, **message_out(updated)}
    await manager.send_to_room(str(room["_id"]), payload)


# ---------- Cuộc gọi ----------
async def on_call_invite(user: dict, ws: WebSocket, data: dict) -> None:
    room = await find_room_of(user, data.get("room_id"))
    if not room:
        return await send_error(ws, "FORBIDDEN", "Bạn không ở trong phòng này")
    await calls.invite(user, ws, room, data.get("media", "audio"))


async def handle_event(user: dict, ws: WebSocket, raw: str) -> None:
    if len(raw) > MAX_FRAME_CHARS:
        return await send_error(ws, "TOO_LARGE", "Tin quá lớn")
    try:
        data = json.loads(raw)
        event_type = data["type"]
    except (ValueError, KeyError, TypeError):
        return await send_error(ws, "BAD_REQUEST", "Tin nhắn phải là JSON có trường 'type'")

    # Bảng điều phối: type -> hàm xử lý
    if event_type == "ping":
        await ws.send_json({"type": "pong"})  # heartbeat: client gửi ping, server trả pong
    elif event_type == "typing.start":
        await on_typing(user, ws, data)
    elif event_type == "typing.stop":
        await on_typing(user, ws, data)
    elif event_type == "message.read":
        await on_message_read(user, ws, data)
    elif event_type == "message.edit":
        await on_message_edit(user, ws, data)
    elif event_type == "message.delete":
        await on_message_delete(user, ws, data)
    elif event_type == "message.send":
        await on_message_send(user, ws, data)
    elif event_type == "message.reaction":
        await on_message_reaction(user, ws, data)
    elif event_type == "call.invite":
        await on_call_invite(user, ws, data)
    elif event_type == "call.accept":
        await calls.accept(user, ws, str(data.get("call_id")))
    elif event_type == "call.reject":
        await calls.reject(user, str(data.get("call_id")))
    elif event_type == "call.end":  # cúp máy / rời cuộc gọi / hủy khi đang đổ chuông
        await calls.leave(str(user["_id"]), str(data.get("call_id")), ws)
    elif event_type in ("webrtc.offer", "webrtc.answer", "webrtc.ice"):
        await calls.relay(user, ws, data)  # chỉ chuyển tiếp tới đúng người nhận
    else:
        await send_error(ws, "UNKNOWN_TYPE", f"Không hỗ trợ sự kiện '{event_type}'")


# ---------- Vòng đời kết nối ----------
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query("")):
    await ws.accept()

    # Trình duyệt không gắn được header tùy ý khi mở WebSocket -> nhận JWT qua query string
    user = await user_from_token(token)
    if not user:
        await ws.close(code=4401)  # 4401: mã đóng tùy chỉnh = chưa xác thực
        return

    uid, username = str(user["_id"]), user["username"]
    # Đăng ký các phòng của user vào manager để biết gửi tin tới đâu
    async for room in db.rooms.find({"members": user["_id"]}, {"members": 1}):
        manager.set_room_members(str(room["_id"]), room["members"])
    became_online = manager.connect(uid, username, ws)

    await ws.send_json({"type": "presence.list", "users": manager.online_user_ids()})
    for status in calls.active_group_status(uid):
        await ws.send_json(status)
    if became_online:
        await manager.broadcast(
            {"type": "presence.update", "user_id": uid, "username": username, "status": "online"}
        )

    try:
        while True:
            # Không nhận được gì (kể cả ping) quá WS_IDLE_TIMEOUT giây -> coi là kết nối chết
            raw = await asyncio.wait_for(ws.receive_text(), WS_IDLE_TIMEOUT)
            try:
                await handle_event(user, ws, raw)
            except WebSocketDisconnect:
                raise
            except Exception:
                log.exception("Lỗi khi xử lý sự kiện WS")
                await send_error(ws, "INTERNAL", "Lỗi máy chủ")
    except (WebSocketDisconnect, asyncio.TimeoutError, RuntimeError):
        pass
    finally:
        offline = manager.disconnect(uid, ws)
        await calls.on_disconnect(uid, ws, offline)
        if offline:
            await manager.broadcast(
                {"type": "presence.update", "user_id": uid, "username": username, "status": "offline"}
            )

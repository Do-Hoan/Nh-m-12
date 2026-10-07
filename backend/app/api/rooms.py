from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..db import db, now
from ..deps import get_current_user
from ..security import to_oid
from ..serializers import message_out

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class ChannelIn(BaseModel):
    name: str = Field(min_length=2, max_length=30, pattern=r"^[a-z0-9_-]+$")


class DMIn(BaseModel):
    username: str


async def room_out(room: dict, me_id) -> dict:
    name = room.get("name")
    if room["type"] == "dm":  # DM hiển thị tên của người còn lại
        other_id = next((m for m in room["members"] if m != me_id), me_id)
        other = await db.users.find_one({"_id": other_id})
        name = other["username"] if other else "unknown"
    return {"id": str(room["_id"]), "type": room["type"], "name": name}


@router.get("")
async def my_rooms(user=Depends(get_current_user)):
    rooms = await db.rooms.find({"members": user["_id"]}).to_list(500)
    return [await room_out(r, user["_id"]) for r in rooms]


@router.get("/public")
async def public_rooms(user=Depends(get_current_user)):
    rooms = await db.rooms.find({"type": "channel"}).to_list(500)
    return [
        {"id": str(r["_id"]), "name": r["name"], "joined": user["_id"] in r["members"]}
        for r in rooms
    ]


@router.post("", status_code=201)
async def create_channel(data: ChannelIn, user=Depends(get_current_user)):
    doc = {
        "type": "channel",
        "name": data.name,
        "members": [user["_id"]],
        "owner_id": user["_id"],
        "created_at": now(),
    }
    try:
        res = await db.rooms.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Tên kênh đã tồn tại")
    return {"id": str(res.inserted_id), "type": "channel", "name": data.name}


@router.post("/dm")
async def open_dm(data: DMIn, user=Depends(get_current_user)):
    other = await db.users.find_one({"username": data.username})
    if not other:
        raise HTTPException(404, "Không tìm thấy người dùng")
    if other["_id"] == user["_id"]:
        raise HTTPException(400, "Không thể nhắn tin cho chính mình")
    key = ":".join(sorted([str(user["_id"]), str(other["_id"])]))
    room = await db.rooms.find_one_and_update(  # lấy phòng cũ hoặc tạo mới (atomic)
        {"dm_key": key},
        {"$setOnInsert": {"type": "dm", "members": [user["_id"], other["_id"]], "created_at": now()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return await room_out(room, user["_id"])


@router.post("/{room_id}/join")
async def join_channel(room_id: str, user=Depends(get_current_user)):
    res = await db.rooms.update_one(
        {"_id": to_oid(room_id), "type": "channel"}, {"$addToSet": {"members": user["_id"]}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Không tìm thấy kênh")
    return {"ok": True}


@router.post("/{room_id}/leave")
async def leave_channel(room_id: str, user=Depends(get_current_user)):
    await db.rooms.update_one(
        {"_id": to_oid(room_id), "type": "channel"}, {"$pull": {"members": user["_id"]}}
    )
    return {"ok": True}


@router.get("/{room_id}/messages")
async def history(
    room_id: str,
    before: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user=Depends(get_current_user),
):
    """Lịch sử phân trang theo cursor: trả `limit` tin có id < `before`, cũ -> mới."""
    oid = to_oid(room_id)
    room = await db.rooms.find_one({"_id": oid, "members": user["_id"]}) if oid else None
    if not room:
        raise HTTPException(403, "Bạn không ở trong phòng này")
    query: dict = {"room_id": oid}
    if before and (b := to_oid(before)):
        query["_id"] = {"$lt": b}
    msgs = await db.messages.find(query).sort("_id", -1).limit(limit).to_list(limit)
    return [message_out(m) for m in reversed(msgs)]

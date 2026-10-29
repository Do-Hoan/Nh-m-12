from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from ..db import db, now
from ..deps import get_current_user
from ..models import message_out, rooms_out
from ..security import to_oid
from ..ws.manager import manager

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class DMIn(BaseModel):
    user_id: str


class GroupIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    member_ids: list[str] = Field(min_length=1, max_length=100)


class MembersIn(BaseModel):
    user_ids: list[str] = Field(min_length=1, max_length=100)


async def existing_user_ids(ids: list[str]) -> list:
    oids = [o for o in (to_oid(i) for i in ids) if o]
    docs = await db.users.find({"_id": {"$in": oids}}, {"_id": 1}).to_list(None)
    return [d["_id"] for d in docs]


async def get_group_or_404(room_id: str, user) -> dict:
    oid = to_oid(room_id)
    room = await db.rooms.find_one({"_id": oid, "type": "group", "members": user["_id"]}) if oid else None
    if not room:
        raise HTTPException(404, "Không tìm thấy nhóm")
    return room


async def push(room: dict, event: str, targets=None) -> None:
    """Gửi sự kiện nhóm kèm dữ liệu phòng mới nhất tới các thành viên đang online."""
    [out] = await rooms_out([room], None)
    await manager.send_to_users(targets if targets is not None else room["members"], {"type": event, "room": out})


@router.get("")
async def my_rooms(user=Depends(get_current_user)):
    rooms = await db.rooms.find({"members": user["_id"]}).sort("created_at", 1).to_list(500)
    return await rooms_out(rooms, user["_id"])


@router.post("/dm")
async def open_dm(data: DMIn, user=Depends(get_current_user)):
    other_id = to_oid(data.user_id)
    other = await db.users.find_one({"_id": other_id}) if other_id else None
    if not other:
        raise HTTPException(404, "Không tìm thấy người dùng")
    if other["_id"] == user["_id"]:
        raise HTTPException(400, "Không thể nhắn tin cho chính mình")
    # dm_key có unique index + upsert atomic -> không bao giờ tạo trùng phòng cho một cặp người
    key = ":".join(sorted([str(user["_id"]), str(other["_id"])]))
    room = await db.rooms.find_one_and_update(
        {"dm_key": key},
        {"$setOnInsert": {"type": "dm", "members": [user["_id"], other["_id"]],
                          "created_by": user["_id"], "created_at": now()}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    manager.set_room_members(str(room["_id"]), room["members"])
    [out] = await rooms_out([room], user["_id"])
    return out


@router.post("/group", status_code=201)
async def create_group(data: GroupIn, user=Depends(get_current_user)):
    members = {user["_id"], *await existing_user_ids(data.member_ids)}
    if len(members) < 2:
        raise HTTPException(400, "Nhóm cần có ít nhất 1 thành viên khác")
    doc = {
        "type": "group", "name": data.name.strip(), "members": [user["_id"], *(members - {user["_id"]})],
        "created_by": user["_id"], "created_at": now(),
    }
    await db.rooms.insert_one(doc)
    manager.set_room_members(str(doc["_id"]), doc["members"])
    await push(doc, "group.created")
    [out] = await rooms_out([doc], user["_id"])
    return out


@router.post("/{room_id}/members")
async def add_members(room_id: str, data: MembersIn, user=Depends(get_current_user)):
    room = await get_group_or_404(room_id, user)
    if room.get("is_default") or room["created_by"] != user["_id"]:
        raise HTTPException(403, "Chỉ người tạo nhóm mới thêm được thành viên")
    new_ids = [i for i in await existing_user_ids(data.user_ids) if i not in room["members"]]
    if not new_ids:
        raise HTTPException(400, "Không có thành viên mới hợp lệ")
    room = await db.rooms.find_one_and_update(
        {"_id": room["_id"]}, {"$addToSet": {"members": {"$each": new_ids}}},
        return_document=ReturnDocument.AFTER,
    )
    manager.set_room_members(room_id, room["members"])
    await push(room, "group.created", targets=new_ids)  # người mới: nhóm xuất hiện ở sidebar
    await push(room, "group.updated", targets=[m for m in room["members"] if m not in new_ids])
    [out] = await rooms_out([room], user["_id"])
    return out


@router.delete("/{room_id}/members/{member_id}")
async def remove_member(room_id: str, member_id: str, user=Depends(get_current_user)):
    room = await get_group_or_404(room_id, user)
    target = to_oid(member_id)
    if room.get("is_default") or room["created_by"] != user["_id"]:
        raise HTTPException(403, "Chỉ người tạo nhóm mới xóa được thành viên")
    if target == user["_id"]:
        raise HTTPException(400, "Muốn rời nhóm hãy dùng chức năng Rời nhóm")
    if target not in room["members"]:
        raise HTTPException(404, "Người này không ở trong nhóm")
    room = await db.rooms.find_one_and_update(
        {"_id": room["_id"]}, {"$pull": {"members": target}}, return_document=ReturnDocument.AFTER
    )
    manager.set_room_members(room_id, room["members"])
    await manager.send_to_user(str(target), {"type": "group.removed", "room_id": room_id})
    await push(room, "group.updated")
    [out] = await rooms_out([room], user["_id"])
    return out


@router.post("/{room_id}/leave")
async def leave_group(room_id: str, user=Depends(get_current_user)):
    room = await get_group_or_404(room_id, user)
    if room.get("is_default"):
        raise HTTPException(400, "Không thể rời phòng chung")
    remaining = [m for m in room["members"] if m != user["_id"]]
    await manager.send_to_user(str(user["_id"]), {"type": "group.removed", "room_id": room_id})
    if not remaining:  # người cuối cùng rời -> xóa nhóm và tin nhắn
        await db.rooms.delete_one({"_id": room["_id"]})
        await db.messages.delete_many({"room_id": room["_id"]})
        manager.drop_room(room_id)
        return {"ok": True}
    update = {"$pull": {"members": user["_id"]}}
    if room["created_by"] == user["_id"]:  # người tạo rời -> chuyển quyền cho người kế tiếp
        update["$set"] = {"created_by": remaining[0]}
    room = await db.rooms.find_one_and_update({"_id": room["_id"]}, update, return_document=ReturnDocument.AFTER)
    manager.set_room_members(room_id, room["members"])
    await push(room, "group.updated")
    return {"ok": True}


@router.get("/{room_id}/messages")
async def history(
    room_id: str,
    before: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user=Depends(get_current_user),
):
    """Lịch sử phân trang theo cursor: trả `limit` tin có id < `before`, thứ tự cũ -> mới."""
    oid = to_oid(room_id)
    room = await db.rooms.find_one({"_id": oid, "members": user["_id"]}) if oid else None
    if not room:
        raise HTTPException(403, "Bạn không ở trong phòng này")
    query: dict = {"room_id": oid}
    if before and (b := to_oid(before)):
        query["_id"] = {"$lt": b}  # ObjectId tăng dần theo thời gian -> dùng làm cursor
    msgs = await db.messages.find(query).sort("_id", -1).limit(limit).to_list(limit)
    return [message_out(m) for m in reversed(msgs)]

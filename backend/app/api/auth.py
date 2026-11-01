from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..db import db, now
from ..deps import get_current_user
from ..models import iso, user_out
from ..security import create_token, hash_password, verify_password
from ..services.storage import is_allowed_image_url
from ..ws.manager import manager

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthIn(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=6, max_length=72)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=40)
    about: str | None = Field(default=None, max_length=280)
    avatar_url: str | None = Field(default=None, max_length=2048)


def auth_response(user: dict) -> dict:
    profile = user_out(user)
    profile["created_at"] = iso(user.get("created_at"))
    return {
        "access_token": create_token(str(user["_id"]), user["username"]),
        "user": profile,
    }


@router.post("/register", status_code=201)
async def register(data: AuthIn):
    doc = {
        "username": data.username,
        "password_hash": await hash_password(data.password),
        "created_at": now(),
    }
    try:
        await db.users.insert_one(doc)  # driver tự thêm doc["_id"]
    except DuplicateKeyError:
        raise HTTPException(409, "Tên đăng nhập đã tồn tại")
    # Tự động vào phòng chung "general"
    general = await db.rooms.find_one_and_update(
        {"is_default": True}, {"$addToSet": {"members": doc["_id"]}}, return_document=ReturnDocument.AFTER
    )
    if general:
        manager.set_room_members(str(general["_id"]), general["members"])
    # Báo cho những người đang online để danh sách người dùng cập nhật ngay
    await manager.broadcast({"type": "user.created", "user": user_out(doc)})
    return auth_response(doc)


@router.post("/login")
async def login(data: AuthIn):
    user = await db.users.find_one({"username": data.username})
    if not user or not await verify_password(data.password, user["password_hash"]):
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    return auth_response(user)


@router.get("/me")
async def me(user=Depends(get_current_user)):
    profile = user_out(user)
    profile["created_at"] = iso(user.get("created_at"))
    return profile


@router.patch("/me")
async def update_me(data: ProfileUpdate, user=Depends(get_current_user)):
    fields = data.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "Không có thông tin nào để cập nhật")

    updates = {}
    if "display_name" in fields:
        display_name = (fields["display_name"] or "").strip()
        updates["display_name"] = display_name or None
    if "about" in fields:
        updates["about"] = (fields["about"] or "").strip()
    if "avatar_url" in fields:
        avatar_url = fields["avatar_url"]
        if avatar_url is not None and not is_allowed_image_url(avatar_url):
            raise HTTPException(400, "Ảnh đại diện phải được tải lên RealChat")
        updates["avatar_url"] = avatar_url

    updated = await db.users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    profile = user_out(updated)
    profile["created_at"] = iso(updated.get("created_at"))
    return profile

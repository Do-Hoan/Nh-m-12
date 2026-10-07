from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from ..db import db, now
from ..deps import get_current_user
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthIn(BaseModel):
    username: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=6, max_length=72)


def auth_response(user: dict) -> dict:
    uid = str(user["_id"])
    return {
        "access_token": create_token(uid, user["username"]),
        "user": {"id": uid, "username": user["username"]},
    }


@router.post("/register", status_code=201)
async def register(data: AuthIn):
    doc = {
        "username": data.username,
        "password_hash": await hash_password(data.password),
        "created_at": now(),
    }
    try:
        await db.users.insert_one(doc)  # pymongo tự thêm doc["_id"]
    except DuplicateKeyError:
        raise HTTPException(409, "Tên đăng nhập đã tồn tại")
    # Tự động vào kênh #general
    await db.rooms.update_one(
        {"type": "channel", "name": "general"}, {"$addToSet": {"members": doc["_id"]}}
    )
    return auth_response(doc)


@router.post("/login")
async def login(data: AuthIn):
    user = await db.users.find_one({"username": data.username})
    if not user or not await verify_password(data.password, user["password_hash"]):
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    return auth_response(user)


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {"id": str(user["_id"]), "username": user["username"]}

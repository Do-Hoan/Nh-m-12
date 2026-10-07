import asyncio
from datetime import timedelta

import bcrypt
import jwt
from bson import ObjectId
from bson.errors import InvalidId

from .config import JWT_ALG, JWT_EXPIRE_MINUTES, JWT_SECRET
from .db import now


async def hash_password(password: str) -> str:
    # bcrypt là hàm blocking -> đẩy sang thread để không chặn event loop
    hashed = await asyncio.to_thread(bcrypt.hashpw, password.encode(), bcrypt.gensalt())
    return hashed.decode()


async def verify_password(password: str, hashed: str) -> bool:
    return await asyncio.to_thread(bcrypt.checkpw, password.encode(), hashed.encode())


def create_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": now() + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


def to_oid(value) -> ObjectId | None:
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None

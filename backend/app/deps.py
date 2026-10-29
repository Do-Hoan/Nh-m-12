from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import db
from .security import decode_token, to_oid

bearer = HTTPBearer(auto_error=False)


async def user_from_token(token: str | None) -> dict | None:
    payload = decode_token(token) if token else None
    oid = to_oid(payload["sub"]) if payload else None
    return await db.users.find_one({"_id": oid}) if oid else None


async def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    user = await user_from_token(cred.credentials if cred else None)
    if not user:
        raise HTTPException(401, "Chưa đăng nhập hoặc token hết hạn")
    return user

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import db
from .security import decode_token, to_oid

bearer = HTTPBearer(auto_error=False)


async def get_current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    payload = decode_token(cred.credentials) if cred else None
    oid = to_oid(payload["sub"]) if payload else None
    user = await db.users.find_one({"_id": oid}) if oid else None
    if not user:
        raise HTTPException(401, "Chưa đăng nhập hoặc token hết hạn")
    return user

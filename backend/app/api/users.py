from fastapi import APIRouter, Depends

from ..db import db
from ..deps import get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(user=Depends(get_current_user)):
    """Danh sách username của những người khác (dùng để mở DM)."""
    docs = await db.users.find({"_id": {"$ne": user["_id"]}}, {"username": 1}).to_list(500)
    return sorted(d["username"] for d in docs)

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import STUN_URLS, TURN_CREDENTIAL, TURN_URL, TURN_USERNAME, VAPID_PUBLIC_KEY
from ..db import db
from ..deps import get_current_user
from ..models import user_out

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users")
async def list_users(user=Depends(get_current_user)):
    """Danh sách người dùng khác (dùng để mở DM / chọn thành viên nhóm)."""
    docs = await db.users.find(
        {"_id": {"$ne": user["_id"]}},
        {"username": 1, "display_name": 1, "about": 1, "avatar_url": 1},
    ).sort("username", 1).to_list(1000)
    return [user_out(d) for d in docs]


@router.get("/ice-servers")
async def ice_servers(user=Depends(get_current_user)):
    """Cấu hình ICE cho WebRTC: STUN công cộng + TURN (đọc từ biến môi trường) để gọi được khác mạng."""
    servers: list[dict] = [{"urls": STUN_URLS}]
    if TURN_URL:
        servers.append(
            {
                "urls": [u.strip() for u in TURN_URL.split(",") if u.strip()],
                "username": TURN_USERNAME,
                "credential": TURN_CREDENTIAL,
            }
        )
    return {"iceServers": servers}


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict[str, str]


@router.get("/push/vapid-public-key")
async def push_vapid_public_key(user=Depends(get_current_user)):
    return {"publicKey": VAPID_PUBLIC_KEY}


@router.post("/push/subscription")
async def save_push_subscription(data: PushSubscription, user=Depends(get_current_user)):
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$addToSet": {"push_subscriptions": data.model_dump()}},
    )
    return {"ok": True}

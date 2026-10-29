from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from .config import DB_NAME, MONGODB_URI

client = AsyncIOMotorClient(MONGODB_URI)
db = client[DB_NAME]

GENERAL_NAME = "general"


def now() -> datetime:
    return datetime.now(timezone.utc)


async def init_db() -> None:
    """Tạo index và phòng chung "general" mặc định (chạy lúc server khởi động)."""
    await db.users.create_index("username", unique=True)
    await db.rooms.create_index("members")
    # dm_key = "<id_nhỏ>:<id_lớn>" -> mỗi cặp user chỉ có đúng 1 phòng DM
    await db.rooms.create_index(
        "dm_key", unique=True, partialFilterExpression={"dm_key": {"$type": "string"}}
    )
    # Phân trang lịch sử: lọc theo room, sắp xếp mới -> cũ
    await db.messages.create_index([("room_id", 1), ("created_at", -1)])
    await db.messages.create_index([("room_id", 1), ("_id", -1)])
    await db.call_logs.create_index([("room_id", 1), ("started_at", -1)])
    # Phòng chung: ai đăng ký cũng được thêm vào (xem api/auth.py)
    await db.rooms.update_one(
        {"is_default": True},
        {
            "$setOnInsert": {
                "type": "group",
                "name": GENERAL_NAME,
                "members": [],
                "created_by": None,
                "created_at": now(),
            }
        },
        upsert=True,
    )

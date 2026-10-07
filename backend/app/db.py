from datetime import datetime, timezone

from pymongo import AsyncMongoClient

from .config import DB_NAME, MONGO_URL

client = AsyncMongoClient(MONGO_URL)
db = client[DB_NAME]


def now() -> datetime:
    return datetime.now(timezone.utc)


async def init_db() -> None:
    """Tạo index và kênh #general mặc định (chạy lúc server khởi động)."""
    await db.users.create_index("username", unique=True)
    await db.rooms.create_index("members")
    # dm_key = "<id_nhỏ>:<id_lớn>" -> mỗi cặp user chỉ có đúng 1 phòng DM
    await db.rooms.create_index(
        "dm_key", unique=True, partialFilterExpression={"dm_key": {"$type": "string"}}
    )
    await db.rooms.create_index(
        "name", unique=True, partialFilterExpression={"type": "channel"}
    )
    # Phân trang lịch sử: lọc theo room, sắp xếp theo _id giảm dần
    await db.messages.create_index([("room_id", 1), ("_id", -1)])
    await db.rooms.update_one(
        {"type": "channel", "name": "general"},
        {"$setOnInsert": {"members": [], "created_at": now()}},
        upsert=True,
    )

"""Chuyển document MongoDB -> JSON trả về client (một nơi duy nhất để định nghĩa hình dạng dữ liệu)."""
from .db import db


def iso(dt) -> str | None:
    # Mongo trả datetime "naive" (UTC), nên bỏ tzinfo rồi thêm "Z" cho thống nhất
    return dt.replace(tzinfo=None).isoformat() + "Z" if dt else None


def user_out(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "username": u["username"],
        "display_name": u.get("display_name") or u["username"],
        "about": u.get("about", ""),
        "avatar_url": u.get("avatar_url"),
    }


def message_out(m: dict) -> dict:
    reactions = {}
    for emoji, users in (m.get("reactions") or {}).items():
        reactions[emoji] = [str(uid) for uid in users]
    content = m["content"]
    if m.get("deleted_at"):
        content = "[tin nhắn đã thu hồi]"
    return {
        "id": str(m["_id"]),
        "room_id": str(m["room_id"]),
        "sender": {"id": str(m["sender_id"]), "username": m["sender_name"]},
        "msg_type": m.get("type", "text"),
        "content": content,
        "ts": iso(m["created_at"]),
        "deleted": bool(m.get("deleted_at")),
        "deleted_at": iso(m.get("deleted_at")),
        "edited": bool(m.get("edited_at")),
        "edited_at": iso(m.get("edited_at")),
        "reactions": reactions,
        "read_by": [str(uid) for uid in (m.get("read_by") or [])],
    }


async def rooms_out(rooms: list[dict], me_id) -> list[dict]:
    """Dựng JSON cho nhiều phòng, chỉ tốn 1 truy vấn để lấy tên thành viên."""
    ids = {uid for r in rooms for uid in r["members"]}
    docs = await db.users.find(
        {"_id": {"$in": list(ids)}},
        {"username": 1, "display_name": 1, "about": 1, "avatar_url": 1},
    ).to_list(None)
    by_id = {d["_id"]: user_out(d) for d in docs}
    out = []
    for r in rooms:
        members = [by_id[m] for m in r["members"] if m in by_id]
        name = r.get("name")
        if r["type"] == "dm":  # DM hiển thị tên của người còn lại
            other = next((m for m in members if m["id"] != str(me_id)), None)
            name = other["username"] if other else "unknown"
        out.append(
            {
                "id": str(r["_id"]),
                "type": r["type"],  # "dm" | "group"
                "name": name,
                "members": members,
                "created_by": str(r["created_by"]) if r.get("created_by") else None,
                "is_default": bool(r.get("is_default")),
            }
        )
    return out

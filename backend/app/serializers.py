def message_out(m: dict) -> dict:
    # Mongo trả datetime "naive" (UTC), nên bỏ tzinfo rồi thêm "Z" cho thống nhất
    ts = m["created_at"].replace(tzinfo=None).isoformat() + "Z"
    return {
        "id": str(m["_id"]),
        "room_id": str(m["room_id"]),
        "sender": {"id": str(m["sender_id"]), "username": m["sender_name"]},
        "content": m["content"],
        "ts": ts,
    }

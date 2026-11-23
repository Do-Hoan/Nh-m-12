import re

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile

from ..config import MAX_IMAGE_BYTES, MAX_MEDIA_BYTES
from ..db import db
from ..deps import get_current_user, user_from_token
from ..security import to_oid
from ..services import storage

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    kind: str = Form("image"),
    room_id: str | None = Form(None),
    user=Depends(get_current_user),
):
    """Upload ảnh/video/audio; chỉ thành viên phòng mới được tải file lên."""
    kind = kind.strip().lower()
    if kind not in ("image", "video", "audio"):
        raise HTTPException(400, "Loại file không hợp lệ")

    if kind in ("video", "audio") and not room_id:
        raise HTTPException(400, "Thiếu room_id cho tin video hoặc audio")

    if room_id:
        room_oid = to_oid(room_id)
        room = await db.rooms.find_one({"_id": room_oid, "members": user["_id"]}) if room_oid else None
        if not room:
            raise HTTPException(403, "Bạn không ở trong phòng này")

    limit = MAX_IMAGE_BYTES if kind == "image" else MAX_MEDIA_BYTES
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "File vượt quá 5MB")
    if not data:
        raise HTTPException(400, "File rỗng")

    try:
        if kind == "image":
            content_type = storage.sniff_image(data)
            if not content_type:
                raise HTTPException(415, "Chỉ hỗ trợ ảnh JPG, PNG, GIF hoặc WEBP")
            url = await storage.save_image(file.filename or "image", data)
        else:
            content_type = storage.sniff_media(data, kind)
            if not content_type:
                raise HTTPException(415, "Chỉ hỗ trợ video MP4, WebM, MOV hoặc audio WebM/MP4")
            url = await storage.save_media(file.filename or kind, data, kind, room_id)
    except storage.MediaError as e:
        raise HTTPException(e.status, e.detail)

    return {"url": url, "msg_type": kind, "content_type": content_type}


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    range_header: str | None = Header(None, alias="Range"),
    token: str | None = Query(None),
):
    """Phục vụ GridFS, hỗ trợ HTTP Range để video/audio có thể tua."""
    found = await storage.get_gridfs_info(file_id)
    if not found:
        raise HTTPException(404, "Không tìm thấy file")

    room_id, content_type, total = found
    if room_id:
        user = await user_from_token(token)
        room_oid = to_oid(room_id)
        if not user or not room_oid:
            raise HTTPException(401, "Cần đăng nhập để xem file")
        room = await db.rooms.find_one({"_id": room_oid, "members": user["_id"]})
        if not room:
            raise HTTPException(403, "Bạn không thuộc phòng chứa file này")

    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            raise HTTPException(416, "Range không hợp lệ")
        start_text, end_text = match.groups()
        start = int(start_text) if start_text else 0
        end = int(end_text) if end_text else min(start + 1024 * 1024 - 1, total - 1)
        if total <= 0 or start >= total or end < start:
            raise HTTPException(416, "Vượt ngoài phạm vi file")
        ranged = await storage.read_gridfs_range(file_id, start, end)
        if not ranged:
            raise HTTPException(404, "Không tìm thấy file")
        data, _, ranged_total = ranged
        return Response(
            data,
            status_code=206,
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{start + len(data) - 1}/{ranged_total}",
                "Content-Length": str(len(data)),
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )

    found = await storage.read_gridfs(file_id)
    if not found:
        raise HTTPException(404, "Không tìm thấy file")
    data, content_type = found
    return Response(
        data,
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ..config import MAX_AUDIO_BYTES, MAX_IMAGE_BYTES, MAX_VIDEO_BYTES
from ..deps import get_current_user
from ..services import storage

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", status_code=201)
async def upload_media(file: UploadFile = File(...), msg_type: str = Form("image"), user=Depends(get_current_user)):
    limits = {"image": MAX_IMAGE_BYTES, "video": MAX_VIDEO_BYTES, "audio": MAX_AUDIO_BYTES}
    if msg_type not in limits:
        raise HTTPException(400, "Loại media không hợp lệ")
    try:
        data = await file.read(limits[msg_type] + 1)
        if len(data) > limits[msg_type]:
            raise HTTPException(413, "Tệp vượt quá giới hạn cho phép")
        if not data:
            raise HTTPException(400, "File rỗng")
        if msg_type == "image":
            url = await storage.save_image(file.filename or msg_type, data)
        else:
            url = await storage.save_media(msg_type, file.filename or msg_type, data)
        return {"url": url, "msg_type": msg_type, "content_type": file.content_type}
    except storage.ImageError as exc:
        raise HTTPException(exc.status, exc.detail)
    finally:
        await file.close()


@router.get("/files/{file_id}")
async def get_file(file_id: str):
    found = await storage.read_gridfs(file_id)
    if not found:
        raise HTTPException(404, "Không tìm thấy file")
    data, content_type = found
    return Response(
        data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )

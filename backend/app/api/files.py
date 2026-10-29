from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from ..config import MAX_IMAGE_BYTES
from ..deps import get_current_user
from ..services import storage

router = APIRouter(prefix="/api", tags=["files"])


@router.post("/upload", status_code=201)
async def upload_image(file: UploadFile, user=Depends(get_current_user)):
    """Nhận ảnh (tối đa 5MB; jpg/png/gif/webp), lưu Cloudinary hoặc GridFS, trả URL để gửi tin nhắn kiểu image."""
    data = await file.read(MAX_IMAGE_BYTES + 1)  # đọc dư 1 byte để biết có vượt giới hạn không
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Ảnh vượt quá 5MB")
    if not data:
        raise HTTPException(400, "File rỗng")
    try:
        url = await storage.save_image(file.filename or "image", data)
    except storage.ImageError as e:
        raise HTTPException(e.status, e.detail)
    return {"url": url}


@router.get("/files/{file_id}")
async def get_file(file_id: str):
    """Phục vụ ảnh lưu trong GridFS. ID là ObjectId khó đoán; thẻ <img> không gửi được header Authorization."""
    found = await storage.read_gridfs(file_id)
    if not found:
        raise HTTPException(404, "Không tìm thấy file")
    data, content_type = found
    return Response(
        data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"},
    )

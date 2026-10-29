"""Lưu ảnh: Cloudinary nếu có cấu hình, ngược lại dùng MongoDB GridFS (không bao giờ ghi ổ đĩa local)."""
import hashlib
import time

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from ..config import (
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    CLOUDINARY_CLOUD_NAME,
    USE_CLOUDINARY,
)
from ..db import db

FILES_PREFIX = "/api/files/"
CLOUDINARY_PREFIX = f"https://res.cloudinary.com/{CLOUDINARY_CLOUD_NAME}/"


class ImageError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def sniff_image(data: bytes) -> str | None:
    """Nhận diện định dạng qua "magic bytes" (không tin tên file/Content-Type do client gửi)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_allowed_image_url(url: str) -> bool:
    """Chỉ cho phép tin nhắn ảnh trỏ tới nơi lưu của chính mình (tránh nhúng URL tùy ý)."""
    if USE_CLOUDINARY:
        return url.startswith(CLOUDINARY_PREFIX)
    return url.startswith(FILES_PREFIX)


async def save_image(filename: str, data: bytes) -> str:
    content_type = sniff_image(data)
    if not content_type:
        raise ImageError(415, "Chỉ hỗ trợ ảnh JPG, PNG, GIF hoặc WEBP")
    if USE_CLOUDINARY:
        return await _upload_cloudinary(filename, data)
    bucket = AsyncIOMotorGridFSBucket(db)
    file_id = await bucket.upload_from_stream(
        filename or "image", data, metadata={"content_type": content_type}
    )
    return f"{FILES_PREFIX}{file_id}"


async def _upload_cloudinary(filename: str, data: bytes) -> str:
    ts = str(int(time.time()))
    # Chữ ký Cloudinary: sha1("timestamp=<ts><api_secret>")
    signature = hashlib.sha1(f"timestamp={ts}{CLOUDINARY_API_SECRET}".encode()).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            url,
            data={"api_key": CLOUDINARY_API_KEY, "timestamp": ts, "signature": signature},
            files={"file": (filename or "image", data)},
        )
    if res.status_code != 200:
        raise ImageError(502, "Không tải ảnh lên Cloudinary được")
    return res.json()["secure_url"]


async def read_gridfs(file_id: str) -> tuple[bytes, str] | None:
    try:
        oid = ObjectId(file_id)
        stream = await AsyncIOMotorGridFSBucket(db).open_download_stream(oid)
    except Exception:
        return None
    data = await stream.read()
    return data, (stream.metadata or {}).get("content_type", "application/octet-stream")

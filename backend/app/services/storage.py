"""Lưu ảnh và media: Cloudinary nếu có cấu hình, ngược lại dùng MongoDB GridFS (không bao giờ ghi ổ đĩa local)."""
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


class MediaError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


# Giữ tên cũ để code upload ảnh và test hiện tại không phải sửa.
ImageError = MediaError


def sniff_image(data: bytes) -> str | None:
    """Nhận diện ảnh qua magic bytes, không tin phần đuôi tên file."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_media(data: bytes, kind: str) -> str | None:
    """Nhận diện video/audio cơ bản; MOV/MP4 dùng ftyp, WebM dùng EBML."""
    if kind == "video":
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "video/mp4" if data[8:12] != b"qt  " else "video/quicktime"
    if kind == "audio":
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "audio/webm"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "audio/mp4"
    return None


def is_allowed_media_url(url: str) -> bool:
    """Chỉ cho phép tin nhắn media trỏ tới Cloudinary/GridFS do chính app tạo."""
    if USE_CLOUDINARY:
        return url.startswith(CLOUDINARY_PREFIX)
    return url.startswith(FILES_PREFIX)


def is_allowed_image_url(url: str) -> bool:
    if USE_CLOUDINARY:
        return url.startswith(CLOUDINARY_PREFIX)
    return url.startswith(FILES_PREFIX)


async def save_image(filename: str, data: bytes, room_id: str | None = None) -> str:
    content_type = sniff_image(data)
    if not content_type:
        raise MediaError(415, "Chỉ hỗ trợ ảnh JPG, PNG, GIF hoặc WEBP")
    if USE_CLOUDINARY:
        return await _upload_cloudinary(filename, data, content_type, "image")
    return await _save_gridfs(filename or "image", data, content_type, room_id)


async def save_media(filename: str, data: bytes, kind: str, room_id: str | None = None) -> str:
    content_type = sniff_media(data, kind)
    if not content_type:
        if kind == "video":
            raise MediaError(415, "Chỉ hỗ trợ video MP4, WebM hoặc MOV")
        raise MediaError(415, "Chỉ hỗ trợ ghi âm WebM hoặc MP4")
    if USE_CLOUDINARY:
        return await _upload_cloudinary(filename, data, content_type, "video")
    return await _save_gridfs(filename or kind, data, content_type, room_id)


async def _save_gridfs(filename: str, data: bytes, content_type: str, room_id: str | None = None) -> str:
    bucket = AsyncIOMotorGridFSBucket(db)
    file_id = await bucket.upload_from_stream(
        filename,
        data,
        metadata={"content_type": content_type, "length": len(data), "room_id": room_id},
    )
    return f"{FILES_PREFIX}{file_id}"


async def _upload_cloudinary(filename: str, data: bytes, content_type: str, resource_type: str) -> str:
    ts = str(int(time.time()))
    signature = hashlib.sha1(f"timestamp={ts}{CLOUDINARY_API_SECRET}".encode()).hexdigest()
    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload"
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            url,
            data={"api_key": CLOUDINARY_API_KEY, "timestamp": ts, "signature": signature},
            files={"file": (filename or resource_type, data, content_type)},
        )
    if res.status_code != 200:
        raise MediaError(502, f"Không tải {resource_type} lên Cloudinary được")
    return res.json()["secure_url"]


async def get_gridfs_info(file_id: str) -> tuple[str | None, str, int] | None:
    try:
        grid_out = await db.fs.files.find_one({"_id": ObjectId(file_id)})
        if not grid_out:
            return None
        metadata = grid_out.get("metadata") or {}
        return metadata.get("room_id"), metadata.get("content_type", "application/octet-stream"), int(grid_out.get("length", 0))
    except Exception:
        return None


async def read_gridfs(file_id: str) -> tuple[bytes, str] | None:
    try:
        oid = ObjectId(file_id)
        bucket = AsyncIOMotorGridFSBucket(db)
        stream = await bucket.open_download_stream(oid)
    except Exception:
        return None
    data = await stream.read()
    return data, (stream.metadata or {}).get("content_type", "application/octet-stream")


async def read_gridfs_range(file_id: str, start: int | None = None, end: int | None = None):
    """Đọc một khoảng GridFS để hỗ trợ HTTP Range của <video>/<audio>."""
    try:
        oid = ObjectId(file_id)
        bucket = AsyncIOMotorGridFSBucket(db)
        grid_out = await db.fs.files.find_one({"_id": oid})
        if not grid_out:
            return None
        total = int(grid_out.get("length", 0))
        if total <= 0:
            total = 0
        stream = await bucket.open_download_stream(oid)
        content_type = (grid_out.get("metadata") or {}).get("content_type", "application/octet-stream")

        if start is None:
            start = 0
        if end is None or end >= total:
            end = total - 1 if total else 0
        if total == 0 or start > end:
            data = b""
        else:
            stream.seek(start)
            data = await stream.read(end - start + 1)
        return data, content_type, total
    except Exception:
        return None

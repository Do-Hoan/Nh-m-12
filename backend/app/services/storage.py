"""Media storage using Cloudinary or MongoDB GridFS; never local disk."""
import hashlib
import time

import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from ..config import CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET, CLOUDINARY_CLOUD_NAME, USE_CLOUDINARY
from ..db import db

FILES_PREFIX = "/api/files/"
CLOUDINARY_PREFIX = f"https://res.cloudinary.com/{CLOUDINARY_CLOUD_NAME}/"


class ImageError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


MediaError = ImageError


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_media(data: bytes, media_type: str) -> str | None:
    if media_type == "image":
        return sniff_image(data)
    if media_type == "video":
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "video/mp4"
    if media_type == "audio":
        if data.startswith(b"OggS"):
            return "audio/ogg"
        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            return "audio/wav"
        if data.startswith(b"ID3") or (len(data) >= 2 and data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "audio/mpeg"
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "audio/webm"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "audio/mp4"
    return None


def is_allowed_image_url(url: str) -> bool:
    return url.startswith(CLOUDINARY_PREFIX) if USE_CLOUDINARY else url.startswith(FILES_PREFIX)


def is_allowed_media_url(url: str, media_type: str) -> bool:
    return is_allowed_image_url(url) if media_type == "image" else (
        url.startswith(CLOUDINARY_PREFIX) if USE_CLOUDINARY else url.startswith(FILES_PREFIX)
    )


async def save_image(filename: str, data: bytes) -> str:
    return await save_media("image", filename, data)


async def save_media(media_type: str, filename: str, data: bytes) -> str:
    content_type = sniff_media(data, media_type)
    if not content_type:
        raise MediaError(415, "Định dạng tệp này chưa được hỗ trợ")
    if USE_CLOUDINARY:
        return await _upload_cloudinary(media_type, filename, data)
    file_id = await AsyncIOMotorGridFSBucket(db).upload_from_stream(
        filename or media_type, data, metadata={"content_type": content_type, "media_type": media_type}
    )
    return f"{FILES_PREFIX}{file_id}"


async def _upload_cloudinary(media_type: str, filename: str, data: bytes) -> str:
    ts = str(int(time.time()))
    signature = hashlib.sha1(f"timestamp={ts}{CLOUDINARY_API_SECRET}".encode()).hexdigest()
    resource_type = "image" if media_type == "image" else "video"
    url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                url,
                data={"api_key": CLOUDINARY_API_KEY, "timestamp": ts, "signature": signature},
                files={"file": (filename or media_type, data)},
            )
        if res.status_code != 200:
            raise MediaError(502, "Hiện chưa thể lưu tệp. Bạn hãy thử lại sau nhé.")
        return res.json()["secure_url"]
    except MediaError:
        raise
    except (httpx.HTTPError, ValueError, KeyError):
        raise MediaError(502, "Hiện chưa thể lưu tệp. Bạn hãy thử lại sau nhé.")


async def read_gridfs(file_id: str) -> tuple[bytes, str] | None:
    try:
        oid = ObjectId(file_id)
        stream = await AsyncIOMotorGridFSBucket(db).open_download_stream(oid)
    except Exception:
        return None
    data = await stream.read()
    return data, (stream.metadata or {}).get("content_type", "application/octet-stream")

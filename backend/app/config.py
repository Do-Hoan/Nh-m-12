"""Toàn bộ cấu hình đọc từ biến môi trường (xem .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()  # đọc file .env ở thư mục đang chạy lệnh (backend/), nếu có


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# --- Database ---
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "chatapp")

# --- Xác thực ---
DEFAULT_JWT_SECRET = "doi-cai-nay-truoc-khi-deploy"
JWT_SECRET = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
JWT_ALG = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24

# --- CORS: để trống = chỉ cùng origin (frontend do chính FastAPI phục vụ nên không cần) ---
CORS_ORIGINS = _list("CORS_ORIGINS")

# --- Lưu ảnh: có đủ 3 biến CLOUDINARY_* thì dùng Cloudinary, không thì dùng MongoDB GridFS ---
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
USE_CLOUDINARY = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB

# --- WebRTC: STUN công cộng + TURN (tùy chọn nhưng cần để gọi khác mạng) ---
STUN_URLS = _list("STUN_URLS", "stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302")
TURN_URL = os.getenv("TURN_URL", "")  # có thể nhiều URL, ngăn bằng dấu phẩy
TURN_USERNAME = os.getenv("TURN_USERNAME", "")
TURN_CREDENTIAL = os.getenv("TURN_CREDENTIAL", "")

# --- Chat / cuộc gọi ---
MAX_MESSAGE_LEN = 2000
CALL_RING_TIMEOUT = float(os.getenv("CALL_RING_TIMEOUT", "30"))  # giây chờ nghe máy
MAX_CALL_PARTICIPANTS = int(os.getenv("MAX_CALL_PARTICIPANTS", "4"))  # mesh: tối đa 4 người
WS_IDLE_TIMEOUT = float(os.getenv("WS_IDLE_TIMEOUT", "60"))  # không nhận gì (kể cả ping) -> đóng

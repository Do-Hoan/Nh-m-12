import os

from dotenv import load_dotenv

load_dotenv()  # đọc file .env ở thư mục đang chạy lệnh (backend/), nếu có

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "chatapp")
JWT_SECRET = os.getenv("JWT_SECRET", "doi-cai-nay-truoc-khi-deploy")
JWT_ALG = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24
MAX_MESSAGE_LEN = 2000

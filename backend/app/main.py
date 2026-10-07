from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import auth, rooms, users
from .db import init_db
from .ws.endpoint import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Chat App", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(ws_router)

# backend/app/main.py -> lên 3 cấp mới tới thư mục gốc dự án, nơi chứa frontend/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Phải mount cuối cùng để không che các route ở trên
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

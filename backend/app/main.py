import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import auth, files, rooms, users
from .config import CORS_ORIGINS, DEFAULT_JWT_SECRET, JWT_SECRET
from .db import init_db
from .ws.endpoint import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if JWT_SECRET == DEFAULT_JWT_SECRET:
        logging.getLogger("uvicorn.error").warning("JWT_SECRET đang dùng giá trị mặc định - hãy đặt biến môi trường trước khi deploy!")
    await init_db()
    yield


app = FastAPI(title="RealChat", lifespan=lifespan)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"]
    )


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}  # Render dùng để kiểm tra service còn sống


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(rooms.router)
app.include_router(files.router)
app.include_router(ws_router)

# Frontend thuần (HTML/CSS/JS) do chính FastAPI phục vụ -> chỉ cần deploy 1 service
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# Phải mount cuối cùng để không che các route ở trên
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

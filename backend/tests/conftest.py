"""Fixture dÃ¹ng chung. Thay Motor báº±ng mongomock-motor (MongoDB giáº£ trong RAM) nÃªn test khÃ´ng cáº§n cÃ i MongoDB."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-123")
import motor.motor_asyncio as motor_mod
from mongomock_motor import AsyncMongoMockClient

# Pháº£i patch TRÆ¯á»šC khi import app.db (nÆ¡i táº¡o client)
motor_mod.AsyncIOMotorClient = AsyncMongoMockClient

import asyncio  # noqa: E402
import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.db import client as mclient  # noqa: E402
from app.main import app  # noqa: E402
from app.ws import calls as calls_mod  # noqa: E402
from app.ws.manager import manager  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:  # cháº¡y lifespan -> init_db (táº¡o phÃ²ng general)
        yield c
    # Dá»n sáº¡ch giá»¯a cÃ¡c test
    asyncio.run(mclient.drop_database(config.DB_NAME))
    manager.sockets.clear(); manager.names.clear(); manager.rooms.clear()
    calls_mod.calls.calls.clear()


def register(client, username, password="secret123"):
    r = client.post("/api/auth/register", json={"username": username, "password": password})
    assert r.status_code == 201, r.text
    d = r.json()
    return {"id": d["user"]["id"], "token": d["access_token"], "h": {"Authorization": "Bearer " + d["access_token"]}}


@pytest.fixture
def make_user(client):
    return lambda name: register(client, name)


@pytest.fixture
def short_ring(monkeypatch):
    monkeypatch.setattr(calls_mod, "CALL_RING_TIMEOUT", 0.3)



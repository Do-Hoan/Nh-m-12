def test_register_returns_token_and_joins_general(client):
    r = client.post("/api/auth/register", json={"username": "anh", "password": "secret123"})
    assert r.status_code == 201
    body = r.json()
    assert body["access_token"] and body["user"]["username"] == "anh"
    rooms = client.get("/api/rooms", headers={"Authorization": "Bearer " + body["access_token"]}).json()
    assert [(x["name"], x["type"], x["is_default"]) for x in rooms] == [("general", "group", True)]


def test_register_duplicate_username_409(client):
    client.post("/api/auth/register", json={"username": "anh", "password": "secret123"})
    r = client.post("/api/auth/register", json={"username": "anh", "password": "other456"})
    assert r.status_code == 409


def test_register_validation(client):
    assert client.post("/api/auth/register", json={"username": "a b", "password": "secret123"}).status_code == 422
    assert client.post("/api/auth/register", json={"username": "binh", "password": "123"}).status_code == 422


def test_login_ok_and_wrong_password(client):
    client.post("/api/auth/register", json={"username": "anh", "password": "secret123"})
    ok = client.post("/api/auth/login", json={"username": "anh", "password": "secret123"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = client.post("/api/auth/login", json={"username": "anh", "password": "sai-mat-khau"})
    assert bad.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer xxx"}).status_code == 401


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect
    import pytest

    with client.websocket_connect("/ws?token=bad") as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401

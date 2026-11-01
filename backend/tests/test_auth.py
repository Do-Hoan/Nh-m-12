def test_register_returns_token_and_joins_general(client):
    r = client.post("/api/auth/register", json={"username": "anh", "password": "secret123"})
    assert r.status_code == 201
    body = r.json()
    assert body["access_token"] and body["user"]["username"] == "anh"
    assert body["user"]["created_at"].endswith("Z")
    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + body["access_token"]}).json()
    assert me["created_at"].endswith("Z")
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


def test_profile_update_persists_display_name_and_about(client, make_user):
    user = make_user("anh")
    other = make_user("binh")
    response = client.patch(
        "/api/auth/me",
        json={"display_name": "  Anh Nguyễn  ", "about": "  Xin chào  "},
        headers=user["h"],
    )
    assert response.status_code == 200
    assert response.json()["username"] == "anh"
    assert response.json()["display_name"] == "Anh Nguyễn"
    assert response.json()["about"] == "Xin chào"
    assert response.json()["avatar_url"] is None

    me = client.get("/api/auth/me", headers=user["h"]).json()
    assert me["display_name"] == "Anh Nguyễn"
    assert me["about"] == "Xin chào"
    listed = client.get("/api/users", headers=other["h"]).json()
    assert listed[0]["display_name"] == "Anh Nguyễn"
    room = client.post("/api/rooms/dm", json={"user_id": other["id"]}, headers=user["h"]).json()
    assert next(member for member in room["members"] if member["id"] == user["id"])["display_name"] == "Anh Nguyễn"


def test_profile_update_avatar_requires_realchat_upload(client, make_user):
    user = make_user("anh")
    headers = user["h"]
    assert client.patch(
        "/api/auth/me",
        json={"avatar_url": "https://example.com/avatar.png"},
        headers=headers,
    ).status_code == 400
    response = client.patch("/api/auth/me", json={"avatar_url": "/api/files/abc"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["avatar_url"] == "/api/files/abc"
    cleared = client.patch("/api/auth/me", json={"avatar_url": None}, headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["avatar_url"] is None


def test_profile_update_validation_and_auth(client, make_user):
    user = make_user("anh")
    assert client.patch("/api/auth/me", json={"about": "x" * 281}, headers=user["h"]).status_code == 422
    assert client.patch("/api/auth/me", json={"display_name": "x" * 41}, headers=user["h"]).status_code == 422
    assert client.patch("/api/auth/me", json={"about": "hello"}).status_code == 401


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect
    import pytest

    with client.websocket_connect("/ws?token=bad") as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401

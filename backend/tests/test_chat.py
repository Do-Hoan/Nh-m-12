import pytest


def ws_url(u):
    return "/ws?token=" + u["token"]


def drain_until(ws, type_):
    """Đọc cho tới khi gặp message có type mong muốn (bỏ qua presence...)."""
    for _ in range(20):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"Không nhận được {type_}")


def open_dm(client, me, other):
    r = client.post("/api/rooms/dm", json={"user_id": other["id"]}, headers=me["h"])
    assert r.status_code == 200, r.text
    return r.json()


def test_dm_is_not_duplicated(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    r1, r2 = open_dm(client, a, b), open_dm(client, b, a)  # mở từ hai phía
    assert r1["id"] == r2["id"]
    assert r1["name"] == "binh" and r2["name"] == "anh"


def test_send_text_message_saved_then_broadcast(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = open_dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "message.send", "room_id": room["id"], "content": "Xin chào", "client_id": "c1"})
        got_b = drain_until(wb, "message.new")
        got_a = drain_until(wa, "message.new")
    assert got_b["content"] == "Xin chào" and got_b["msg_type"] == "text"
    assert got_b["sender"]["username"] == "anh" and got_a["client_id"] == "c1"
    # đã lưu vào DB -> có trong lịch sử
    hist = client.get(f"/api/rooms/{room['id']}/messages", headers=b["h"]).json()
    assert [m["content"] for m in hist] == ["Xin chào"]


def test_non_member_cannot_send(client, make_user):
    a, b, c = make_user("anh"), make_user("binh"), make_user("chi_")
    room = open_dm(client, a, b)
    with client.websocket_connect(ws_url(c)) as wc:
        wc.send_json({"type": "message.send", "room_id": room["id"], "content": "chen ngang"})
        assert drain_until(wc, "error")["code"] == "FORBIDDEN"
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=c["h"]).status_code == 403
    assert client.get(f"/api/rooms/{room['id']}/messages", headers=a["h"]).json() == []


def test_invalid_image_url_rejected(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = open_dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa:
        wa.send_json({"type": "message.send", "room_id": room["id"], "msg_type": "image",
                      "content": "https://evil.example/x.png"})
        assert drain_until(wa, "error")["code"] == "INVALID_CONTENT"


def test_ping_pong_and_unknown_type(client, make_user):
    a = make_user("anh")
    with client.websocket_connect(ws_url(a)) as wa:
        wa.send_json({"type": "ping"})
        assert drain_until(wa, "pong")
        wa.send_json({"type": "nope"})
        assert drain_until(wa, "error")["code"] == "UNKNOWN_TYPE"


def test_presence_multi_tab(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    with client.websocket_connect(ws_url(a)) as wa:
        with client.websocket_connect(ws_url(b)) as wb1:
            while drain_until(wa, "presence.update")["username"] != "binh":
                pass
            with client.websocket_connect(ws_url(b)) as wb2:
                pass  # tab 2 đóng -> vẫn online vì còn tab 1
            wb1.send_json({"type": "ping"})
            assert drain_until(wb1, "pong")
        msg = drain_until(wa, "presence.update")
        assert msg["status"] == "offline" and msg["username"] == "binh"


def test_pagination_cursor(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = open_dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa:
        for i in range(5):
            wa.send_json({"type": "message.send", "room_id": room["id"], "content": f"m{i}"})
            drain_until(wa, "message.new")
    url = f"/api/rooms/{room['id']}/messages"
    page1 = client.get(url + "?limit=2", headers=a["h"]).json()
    assert [m["content"] for m in page1] == ["m3", "m4"]
    page2 = client.get(url + f"?limit=2&before={page1[0]['id']}", headers=a["h"]).json()
    assert [m["content"] for m in page2] == ["m1", "m2"]


def test_group_lifecycle(client, make_user):
    a, b, c = make_user("anh"), make_user("binh"), make_user("chi_")
    g = client.post("/api/rooms/group", json={"name": "Nhóm học", "member_ids": [b["id"]]}, headers=a["h"]).json()
    assert {m["username"] for m in g["members"]} == {"anh", "binh"}
    # thêm thành viên: chỉ người tạo
    assert client.post(f"/api/rooms/{g['id']}/members", json={"user_ids": [c["id"]]}, headers=b["h"]).status_code == 403
    assert client.post(f"/api/rooms/{g['id']}/members", json={"user_ids": [c["id"]]}, headers=a["h"]).status_code == 200
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(c)) as wc:
        wa.send_json({"type": "message.send", "room_id": g["id"], "content": "chào nhóm"})
        assert drain_until(wc, "message.new")["content"] == "chào nhóm"
        # xóa thành viên rồi c không còn gửi/nhận được
        assert client.delete(f"/api/rooms/{g['id']}/members/{c['id']}", headers=a["h"]).status_code == 200
        assert drain_until(wc, "group.removed")["room_id"] == g["id"]
    assert client.get(f"/api/rooms/{g['id']}/messages", headers=c["h"]).status_code == 403
    # b rời nhóm
    assert client.post(f"/api/rooms/{g['id']}/leave", headers=b["h"]).status_code == 200
    rooms_b = [r["name"] for r in client.get("/api/rooms", headers=b["h"]).json()]
    assert "Nhóm học" not in rooms_b


def test_cannot_leave_general(client, make_user):
    a = make_user("anh")
    general = client.get("/api/rooms", headers=a["h"]).json()[0]
    assert client.post(f"/api/rooms/{general['id']}/leave", headers=a["h"]).status_code == 400


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_upload_validation(client, make_user):
    a = make_user("anh")
    bad = client.post("/api/upload", files={"file": ("x.txt", b"hello", "text/plain")}, headers=a["h"])
    assert bad.status_code == 415
    big = client.post("/api/upload", files={"file": ("x.png", PNG + b"0" * (5 * 1024 * 1024), "image/png")}, headers=a["h"])
    assert big.status_code == 413
    assert client.post("/api/upload", files={"file": ("x.png", PNG, "image/png")}).status_code == 401


def test_upload_ok_and_image_message(client, make_user, monkeypatch):
    from app.services import storage

    async def fake_save(filename, data):  # bỏ qua GridFS (mongomock không hỗ trợ)
        return "/api/files/abc"

    monkeypatch.setattr(storage, "save_image", fake_save)
    a, b = make_user("anh"), make_user("binh")
    r = client.post("/api/upload", files={"file": ("x.png", PNG, "image/png")}, headers=a["h"])
    assert r.status_code == 201
    room = open_dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa:
        wa.send_json({"type": "message.send", "room_id": room["id"], "msg_type": "image", "content": r.json()["url"]})
        m = drain_until(wa, "message.new")
    assert m["msg_type"] == "image" and m["content"] == "/api/files/abc"


def test_ice_servers_includes_turn(client, make_user, monkeypatch):
    from app.api import users

    monkeypatch.setattr(users, "TURN_URL", "turn:t.example:80,turns:t.example:443")
    monkeypatch.setattr(users, "TURN_USERNAME", "u")
    monkeypatch.setattr(users, "TURN_CREDENTIAL", "p")
    a = make_user("anh")
    servers = client.get("/api/ice-servers", headers=a["h"]).json()["iceServers"]
    assert servers[1] == {"urls": ["turn:t.example:80", "turns:t.example:443"], "username": "u", "credential": "p"}


def test_edit_delete_react_read_typing(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = open_dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "message.send", "room_id": room["id"], "content": "hi"})
        mid = drain_until(wb, "message.new")["id"]
        drain_until(wa, "message.new")

        wb.send_json({"type": "message.edit", "room_id": room["id"], "message_id": mid, "content": "x"})
        assert drain_until(wb, "error")["code"] == "FORBIDDEN"

        wa.send_json({"type": "message.edit", "room_id": room["id"], "message_id": mid, "content": "hello"})
        assert drain_until(wb, "message.edited")["content"] == "hello"

        wb.send_json({"type": "message.reaction", "room_id": room["id"], "message_id": mid, "emoji": "👍"})
        assert drain_until(wa, "message.reaction")["reactions"]["👍"] == [b["id"]]

        wb.send_json({"type": "message.read", "room_id": room["id"], "message_id": mid})
        assert drain_until(wa, "message.read")["user_id"] == b["id"]

        wa.send_json({"type": "typing.start", "room_id": room["id"]})
        assert drain_until(wb, "typing.start")["username"] == "anh"

        wa.send_json({"type": "message.delete", "room_id": room["id"], "message_id": mid})
        assert drain_until(wb, "message.deleted")["deleted"] is True
        wa.send_json({"type": "message.edit", "room_id": room["id"], "message_id": mid, "content": "again"})
        assert drain_until(wa, "error")["code"] == "NOT_FOUND"

def ws_url(u):
    return "/ws?token=" + u["token"]


def drain_until(ws, type_):
    for _ in range(30):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"Không nhận được {type_}")


def dm(client, me, other):
    return client.post("/api/rooms/dm", json={"user_id": other["id"]}, headers=me["h"]).json()


def test_call_1to1_signaling_flow(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "video"})
        ringing = drain_until(wa, "call.ringing")
        incoming = drain_until(wb, "call.incoming")
        assert incoming["call_id"] == ringing["call_id"] and incoming["from"]["username"] == "anh"
        assert incoming["media"] == "video" and incoming["is_group"] is False
        cid = ringing["call_id"]

        wb.send_json({"type": "call.accept", "call_id": cid})
        joined = drain_until(wb, "call.joined")
        assert [p["username"] for p in joined["participants"]] == ["anh"]  # B sẽ offer tới A
        assert drain_until(wa, "call.participant_joined")["user"]["username"] == "binh"

        # B -> A: offer; A -> B: answer; ICE hai chiều. Server chỉ chuyển tiếp.
        wb.send_json({"type": "webrtc.offer", "call_id": cid, "to": a["id"], "payload": {"sdp": "OFFER"}})
        off = drain_until(wa, "webrtc.offer")
        assert off["from"] == b["id"] and off["payload"] == {"sdp": "OFFER"}
        wa.send_json({"type": "webrtc.answer", "call_id": cid, "to": b["id"], "payload": {"sdp": "ANS"}})
        assert drain_until(wb, "webrtc.answer")["payload"] == {"sdp": "ANS"}
        wa.send_json({"type": "webrtc.ice", "call_id": cid, "to": b["id"], "payload": {"candidate": "c1"}})
        assert drain_until(wb, "webrtc.ice")["payload"] == {"candidate": "c1"}

        wa.send_json({"type": "call.end", "call_id": cid})
        assert drain_until(wb, "call.ended")["reason"] == "ended"


def test_call_offline_user(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "audio"})
        assert drain_until(wa, "call.unavailable")["reason"] == "offline"


def test_call_reject(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "audio"})
        cid = drain_until(wb, "call.incoming")["call_id"]
        wb.send_json({"type": "call.reject", "call_id": cid})
        assert drain_until(wa, "call.rejected")["user"]["username"] == "binh"
        assert drain_until(wa, "call.ended")["reason"] == "rejected"


def test_call_busy(client, make_user):
    a, b, c = make_user("anh"), make_user("binh"), make_user("chi_")
    room_ab, room_cb = dm(client, a, b), dm(client, c, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb, \
            client.websocket_connect(ws_url(c)) as wc:
        wa.send_json({"type": "call.invite", "room_id": room_ab["id"], "media": "audio"})
        cid = drain_until(wb, "call.incoming")["call_id"]
        wb.send_json({"type": "call.accept", "call_id": cid})
        drain_until(wb, "call.joined")
        wc.send_json({"type": "call.invite", "room_id": room_cb["id"], "media": "audio"})
        assert drain_until(wc, "call.busy")["reason"] == "busy"


def test_call_no_answer_timeout(client, make_user, short_ring):
    a, b = make_user("anh"), make_user("binh")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "audio"})
        drain_until(wb, "call.incoming")
        assert drain_until(wb, "call.dismiss")["reason"] == "timeout"
        assert drain_until(wa, "call.ended")["reason"] == "timeout"


def test_call_cancel_while_ringing(client, make_user):
    a, b = make_user("anh"), make_user("binh")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "audio"})
        cid = drain_until(wb, "call.incoming")["call_id"]
        wa.send_json({"type": "call.end", "call_id": cid})
        assert drain_until(wb, "call.dismiss")["reason"] == "cancelled"


def test_relay_rejects_outsider(client, make_user):
    a, b, c = make_user("anh"), make_user("binh"), make_user("chi_")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb, \
            client.websocket_connect(ws_url(c)) as wc:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "audio"})
        cid = drain_until(wb, "call.incoming")["call_id"]
        wb.send_json({"type": "call.accept", "call_id": cid})
        drain_until(wb, "call.joined")
        wc.send_json({"type": "webrtc.offer", "call_id": cid, "to": a["id"], "payload": {"sdp": "x"}})
        assert drain_until(wc, "error")["code"] == "NO_CALL"
        wc.send_json({"type": "call.accept", "call_id": cid})  # không thuộc phòng -> không vào được
        assert drain_until(wc, "error")["code"] == "NO_CALL"


def test_group_call_limit(client, make_user, monkeypatch):
    from app.ws import calls as calls_mod

    monkeypatch.setattr(calls_mod, "MAX_CALL_PARTICIPANTS", 3)
    users = [make_user(n) for n in ("anh", "binh", "chi_", "dung")]
    g = client.post("/api/rooms/group", json={"name": "Nhóm gọi", "member_ids": [u["id"] for u in users[1:]]},
                    headers=users[0]["h"]).json()
    a, b, c, d = users
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb, \
            client.websocket_connect(ws_url(c)) as wc, client.websocket_connect(ws_url(d)) as wd:
        wa.send_json({"type": "call.invite", "room_id": g["id"], "media": "video"})
        inc = drain_until(wb, "call.incoming")
        assert inc["is_group"] is True
        cid = inc["call_id"]
        drain_until(wc, "call.incoming"); drain_until(wd, "call.incoming")

        wb.send_json({"type": "call.accept", "call_id": cid})
        assert [p["username"] for p in drain_until(wb, "call.joined")["participants"]] == ["anh"]
        wc.send_json({"type": "call.accept", "call_id": cid})
        assert {p["username"] for p in drain_until(wc, "call.joined")["participants"]} == {"anh", "binh"}
        # đã đủ 3 người (giới hạn đang đặt = 3) -> người thứ 4 bị từ chối
        wd.send_json({"type": "call.accept", "call_id": cid})
        assert drain_until(wd, "error")["code"] == "CALL_FULL"

        # c cúp máy, cuộc gọi nhóm vẫn tiếp tục
        wc.send_json({"type": "call.end", "call_id": cid})
        assert drain_until(wa, "call.participant_left")["user"]["username"] == "chi_"
        wa.send_json({"type": "ping"})
        assert drain_until(wa, "pong")


def test_call_logs_written(client, make_user):
    import asyncio
    from app.db import db

    a, b = make_user("anh"), make_user("binh")
    room = dm(client, a, b)
    with client.websocket_connect(ws_url(a)) as wa, client.websocket_connect(ws_url(b)) as wb:
        wa.send_json({"type": "call.invite", "room_id": room["id"], "media": "audio"})
        cid = drain_until(wb, "call.incoming")["call_id"]
        wb.send_json({"type": "call.accept", "call_id": cid})
        drain_until(wb, "call.joined")
        wb.send_json({"type": "call.end", "call_id": cid})
        drain_until(wa, "call.ended")
    log = asyncio.run(db.call_logs.find_one({"call_id": cid}))
    assert log["status"] == "answered" and log["media"] == "audio"

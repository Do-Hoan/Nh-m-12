"""Quản lý cuộc gọi (signaling). Server KHÔNG xử lý âm thanh/hình ảnh: media đi trực tiếp giữa các trình duyệt
(WebRTC peer-to-peer). Server chỉ (1) quản lý trạng thái cuộc gọi: đổ chuông, nghe máy, bận, timeout...
và (2) chuyển tiếp (relay) offer/answer/ICE giữa các bên.

Quy ước mesh: người MỚI VÀO cuộc gọi sẽ tạo offer tới từng người ĐÃ Ở TRONG cuộc gọi.
  - Gọi 1-1: B nghe máy -> B offer tới A.
  - Gọi nhóm: D tham gia -> D offer tới A, B, C. Mỗi cặp người có đúng một peer connection.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from ..config import CALL_RING_TIMEOUT, MAX_CALL_PARTICIPANTS
from ..db import db, now
from ..models import user_out
from ..security import to_oid
from .manager import manager

log = logging.getLogger(__name__)

MAX_SIGNAL_BYTES = 64 * 1024


@dataclass
class Call:
    id: str
    room_id: str
    is_group: bool
    media: str  # "audio" | "video"
    initiator: str
    member_ids: set[str]  # thành viên phòng tại thời điểm bắt đầu (được phép tham gia)
    users: dict[str, dict] = field(default_factory=dict)  # user_id -> {"id","username"}
    participants: dict[str, WebSocket] = field(default_factory=dict)  # đã vào cuộc gọi: user_id -> socket
    ringing: set[str] = field(default_factory=set)  # đang đổ chuông
    ever_joined: set[str] = field(default_factory=set)
    started_at: object = field(default_factory=now)
    answered_at: object = None
    timer: asyncio.Task | None = None

    def user_list(self, exclude: str | None = None) -> list[dict]:
        return [self.users[u] for u in self.participants if u != exclude]


class CallManager:
    def __init__(self) -> None:
        self.calls: dict[str, Call] = {}

    # ---------- tiện ích ----------
    def busy(self, uid: str) -> bool:
        return any(uid in c.participants or uid in c.ringing for c in self.calls.values())

    def call_of_room(self, room_id: str) -> Call | None:
        return next((c for c in self.calls.values() if c.room_id == room_id), None)

    def active_group_status(self, uid: str) -> list[dict]:
        """Các cuộc gọi nhóm đang diễn ra mà user có quyền tham gia (gửi khi vừa kết nối WS)."""
        return [
            {"type": "call.status", "room_id": c.room_id, "call_id": c.id, "media": c.media,
             "participants": c.user_list()}
            for c in self.calls.values() if c.is_group and uid in c.member_ids
        ]

    async def _err(self, ws: WebSocket, code: str, detail: str, **extra) -> None:
        await manager.send_to_ws(ws, {"type": "error", "code": code, "detail": detail, **extra})

    async def _publish_status(self, call: Call | None, room_id: str) -> None:
        """Báo cho cả phòng nhóm biết đang có cuộc gọi (để hiện nút "Tham gia")."""
        if call is not None and not call.is_group:
            return
        payload = {
            "type": "call.status",
            "room_id": room_id,
            "call_id": call.id if call else None,
            "media": call.media if call else None,
            "participants": call.user_list() if call else [],
        }
        await manager.send_to_room(room_id, payload)

    # ---------- mời ----------
    async def invite(self, user: dict, ws: WebSocket, room: dict, media: str) -> None:
        uid = str(user["_id"])
        room_id = str(room["_id"])
        if media not in ("audio", "video"):
            return await self._err(ws, "BAD_REQUEST", "media phải là 'audio' hoặc 'video'")
        if self.busy(uid):
            return await self._err(ws, "ALREADY_IN_CALL", "Bạn đang trong một cuộc gọi khác")
        existing = self.call_of_room(room_id)
        if existing:
            return await self._err(
                ws, "CALL_EXISTS", "Phòng này đang có cuộc gọi, hãy tham gia", call_id=existing.id
            )

        is_group = room["type"] == "group"
        member_ids = {str(m) for m in room["members"]}
        others = member_ids - {uid}
        online = [m for m in others if manager.is_online(m)]
        targets = [m for m in online if not self.busy(m)]
        if not targets:
            # Gọi 1-1: phân biệt "bận" và "không online"
            reason = "busy" if online else "offline"
            return await manager.send_to_ws(
                ws, {"type": "call.busy" if reason == "busy" else "call.unavailable",
                     "room_id": room_id, "reason": reason}
            )

        call = Call(
            id=uuid.uuid4().hex, room_id=room_id, is_group=is_group, media=media,
            initiator=uid, member_ids=member_ids,
        )
        docs = await db.users.find({"_id": {"$in": [to_oid(m) for m in member_ids]}}, {"username": 1}).to_list(None)
        call.users = {str(d["_id"]): user_out(d) for d in docs}
        call.participants[uid] = ws
        call.ever_joined.add(uid)
        call.ringing = set(targets)
        self.calls[call.id] = call

        await manager.send_to_ws(
            ws, {"type": "call.ringing", "call_id": call.id, "room_id": room_id, "media": media,
                 "is_group": is_group}
        )
        incoming = {
            "type": "call.incoming", "call_id": call.id, "room_id": room_id, "media": media,
            "is_group": is_group, "room_name": room.get("name"), "from": call.users[uid],
        }
        await manager.send_to_users(targets, incoming)
        await self._publish_status(call, room_id)
        call.timer = asyncio.create_task(self._ring_timeout(call.id))

    async def _ring_timeout(self, call_id: str) -> None:
        await asyncio.sleep(CALL_RING_TIMEOUT)
        call = self.calls.get(call_id)
        if not call or not call.ringing:
            return
        missed, call.ringing = call.ringing, set()
        # Người chưa trả lời: tắt popup, ghi nhận cuộc gọi nhỡ
        await manager.send_to_users(missed, {"type": "call.dismiss", "call_id": call.id, "reason": "timeout"})
        await self._maybe_finish(call, "timeout")

    # ---------- nghe máy / tham gia ----------
    async def accept(self, user: dict, ws: WebSocket, call_id: str) -> None:
        uid = str(user["_id"])
        call = self.calls.get(call_id)
        if not call or uid not in call.member_ids:
            return await self._err(ws, "NO_CALL", "Cuộc gọi không còn tồn tại")
        if uid in call.participants:
            return
        if self.busy(uid) and uid not in call.ringing:
            return await self._err(ws, "ALREADY_IN_CALL", "Bạn đang trong một cuộc gọi khác")
        if len(call.participants) >= MAX_CALL_PARTICIPANTS:
            return await self._err(
                ws, "CALL_FULL", f"Cuộc gọi đã đủ {MAX_CALL_PARTICIPANTS} người, không thể tham gia thêm",
                call_id=call.id,
            )

        existing = call.user_list()
        call.participants[uid] = ws
        call.ever_joined.add(uid)
        call.ringing.discard(uid)
        if call.answered_at is None:
            call.answered_at = now()

        # Người vào: nhận danh sách người đang ở trong cuộc gọi -> tự tạo offer tới từng người
        await manager.send_to_ws(
            ws, {"type": "call.joined", "call_id": call.id, "room_id": call.room_id, "media": call.media,
                 "is_group": call.is_group, "participants": existing}
        )
        # Người đã ở trong: biết có người mới, chờ nhận offer
        await self._to_participants(call, {"type": "call.participant_joined", "call_id": call.id,
                                           "user": call.users[uid]}, exclude=uid)
        # Các tab khác của chính user này: đóng popup đổ chuông
        for other in list(manager.sockets.get(uid, ())):
            if other is not ws:
                await manager.send_to_ws(other, {"type": "call.dismiss", "call_id": call.id, "reason": "handled"})
        await self._publish_status(call, call.room_id)

    # ---------- từ chối ----------
    async def reject(self, user: dict, call_id: str) -> None:
        uid = str(user["_id"])
        call = self.calls.get(call_id)
        if not call or uid not in call.ringing:
            return
        call.ringing.discard(uid)
        await manager.send_to_user(uid, {"type": "call.dismiss", "call_id": call.id, "reason": "rejected"})
        await self._to_participants(call, {"type": "call.rejected", "call_id": call.id, "user": call.users[uid]})
        await self._maybe_finish(call, "rejected")

    # ---------- cúp máy / rời ----------
    async def leave(self, uid: str, call_id: str, ws: WebSocket | None = None) -> None:
        call = self.calls.get(call_id)
        if not call:
            return
        if uid in call.participants and (ws is None or call.participants[uid] is ws):
            del call.participants[uid]
            await self._to_participants(call, {"type": "call.participant_left", "call_id": call.id,
                                               "user": call.users[uid]})
        elif uid in call.ringing and ws is None:
            call.ringing.discard(uid)
        else:
            return
        await self._maybe_finish(call, "ended")
        if call.id in self.calls:
            await self._publish_status(call, call.room_id)

    async def on_disconnect(self, uid: str, ws: WebSocket, last_socket: bool) -> None:
        """Mất kết nối giữa chừng -> coi như cúp máy."""
        for call in list(self.calls.values()):
            if call.participants.get(uid) is ws:
                await self.leave(uid, call.id, ws)
            elif last_socket and uid in call.ringing:
                call.ringing.discard(uid)
                await self._maybe_finish(call, "rejected")

    async def _maybe_finish(self, call: Call, reason: str) -> None:
        """Kết thúc cuộc gọi khi không còn ai để nói chuyện cùng."""
        if call.id not in self.calls:
            return
        if len(call.participants) == 0 or (len(call.participants) <= 1 and not call.ringing):
            if call.answered_at is not None:
                reason = "ended"
            elif reason == "ended":
                reason = "cancelled"  # người gọi tự cúp khi chưa ai nghe máy
            await self._end(call, reason)

    async def _end(self, call: Call, reason: str) -> None:
        self.calls.pop(call.id, None)
        if call.timer and call.timer is not asyncio.current_task():
            call.timer.cancel()
        payload = {"type": "call.ended", "call_id": call.id, "room_id": call.room_id, "reason": reason}
        await self._to_participants(call, payload)
        if call.ringing:  # initiator cúp khi chưa ai nghe máy
            await manager.send_to_users(call.ringing, {"type": "call.dismiss", "call_id": call.id,
                                                       "reason": "cancelled"})
        if call.is_group:
            await self._publish_status(None, call.room_id)
        ended = now()
        try:
            await db.call_logs.insert_one({
                "call_id": call.id,
                "room_id": to_oid(call.room_id),
                "type": "group" if call.is_group else "dm",
                "media": call.media,
                "initiator_id": to_oid(call.initiator),
                "participants": [to_oid(u) for u in call.ever_joined],
                "started_at": call.started_at,
                "answered_at": call.answered_at,
                "ended_at": ended,
                "duration_s": int((ended - call.answered_at).total_seconds()) if call.answered_at else 0,
                "status": "answered" if call.answered_at else reason,  # rejected | timeout | ended(hủy)
            })
        except Exception:
            log.exception("Không ghi được call_logs")

    async def _to_participants(self, call: Call, payload: dict, exclude: str | None = None) -> None:
        for u, sock in list(call.participants.items()):
            if u != exclude:
                await manager.send_to_ws(sock, payload)

    # ---------- relay SDP/ICE ----------
    async def relay(self, user: dict, ws: WebSocket, data: dict) -> None:
        uid = str(user["_id"])
        call = self.calls.get(str(data.get("call_id")))
        target = str(data.get("to"))
        if (not call or call.participants.get(uid) is not ws or target not in call.participants
                or target == uid):
            return await self._err(ws, "NO_CALL", "Không thể chuyển tiếp: không cùng cuộc gọi")
        if len(str(data.get("payload"))) > MAX_SIGNAL_BYTES:
            return await self._err(ws, "TOO_LARGE", "Dữ liệu signaling quá lớn")
        # Chỉ chuyển tiếp, không đọc nội dung SDP/ICE
        await manager.send_to_ws(
            call.participants[target],
            {"type": data["type"], "call_id": call.id, "from": uid, "payload": data.get("payload")},
        )


calls = CallManager()

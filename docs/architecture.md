# Kiến trúc hệ thống

```
 Trình duyệt (HTML/CSS/JS thuần)                         Internet
 ┌───────────────────────────┐   HTTPS (REST)    ┌─────────────────────────┐   ┌──────────────┐
 │ index.html, css/, js/     │ ───────────────▶  │  FastAPI (1 service)    │──▶│ MongoDB Atlas│
 │  - app.js  (chat)         │   WSS (/ws)       │  - /api/*  REST         │   └──────────────┘
 │  - calls.js (WebRTC)      │ ◀══════════════▶  │  - /ws     WebSocket    │   ┌──────────────┐
 └────────────┬──────────────┘                   │  - /       StaticFiles  │──▶│ Cloudinary   │
              │  media P2P (SRTP)                └─────────────────────────┘   └──────────────┘
              ▼
      Trình duyệt khác  ◀── STUN / TURN (Metered) khi hai người ở mạng khác nhau
```

Chỉ cần deploy **một service**: FastAPI vừa phục vụ API, WebSocket, vừa phục vụ file tĩnh.

## Cấu trúc mã

```
backend/app/
├── main.py          khởi tạo app, CORS, /healthz, mount static
├── config.py        đọc biến môi trường
├── db.py            Motor client, index, seed phòng "general"
├── models.py        chuyển document Mongo -> JSON
├── security.py      bcrypt + JWT
├── deps.py          xác thực cho REST và WS
├── api/             routers REST: auth, users (+ice-servers), rooms, files
├── services/        storage.py: Cloudinary hoặc GridFS
└── ws/
    ├── manager.py   ConnectionManager: kết nối theo user_id và theo room
    ├── calls.py     CallManager: trạng thái cuộc gọi + relay signaling
    └── endpoint.py  /ws: xác thực, heartbeat, điều phối sự kiện
backend/static/      giao diện
backend/tests/       pytest (dùng mongomock-motor, không cần MongoDB)
```

## REST và WebSocket

| | REST | WebSocket |
|---|---|---|
| Dùng cho | Đăng ký/đăng nhập, danh sách, tạo nhóm, thành viên, lịch sử (phân trang), upload ảnh, cấu hình ICE | Tin nhắn mới, presence, signaling cuộc gọi, sự kiện nhóm |
| Lý do | Cần mã trạng thái, phân trang, multipart | Cần hai chiều, độ trễ thấp |

## ConnectionManager

```
sockets: user_id -> {WebSocket, WebSocket, ...}   (một user nhiều tab)
rooms:   room_id -> {user_id, ...}                (để gửi tới cả phòng mà không đọc DB mỗi tin)
```

- `presence.update` chỉ phát khi tab đầu tiên mở / tab cuối cùng đóng.
- `rooms` được đồng bộ khi kết nối, khi tạo/sửa nhóm và khi mở DM. DB vẫn là nguồn sự thật cho việc kiểm tra quyền.
- Vì trạng thái nằm trong RAM của tiến trình, **chỉ chạy 1 worker**. Muốn nhiều instance cần Redis Pub/Sub (chưa làm).

## Vòng đời tin nhắn

```
Client gửi message.send
   │
   ▼  người gửi thuộc phòng? ── không ──▶ error FORBIDDEN
   │ có
   ▼  lưu MongoDB (messages)
   ▼  manager.send_to_room → message.new tới mọi tab của mọi thành viên online
```

Luôn **lưu DB trước, broadcast sau**: nếu lỗi giữa chừng thì không có tin "ma" (người nhận thấy nhưng không có trong lịch sử).

## Cuộc gọi WebRTC

Server không chạm vào media. `CallManager` chỉ giữ trạng thái (đổ chuông, ai đã vào, hết giờ 30s, bận) và chuyển tiếp offer/answer/ICE tới đúng người. Gọi nhóm dùng **mesh**: mỗi cặp một `RTCPeerConnection`, người mới vào offer tới mọi người đã có mặt; giới hạn 4 người vì băng thông upload tăng theo số người (n-1 luồng). Chi tiết ở [protocol.md](protocol.md).

## Xác thực

1. `POST /api/auth/login` trả JWT (HS256, hạn 24h).
2. REST dùng `Authorization: Bearer`; WebSocket dùng `?token=` và đóng mã `4401` nếu sai.
3. Đăng xuất: client xóa token và đóng WebSocket (JWT không trạng thái nên không cần endpoint phía server).

# RealChat — Ứng dụng chat real-time học WebSocket

> Đồ án môn Lập trình mạng. RealChat là một ứng dụng chat nhóm và chat riêng theo thời gian thực, lấy cảm hứng thiết kế từ [Rocket.Chat](https://www.rocket.chat/), được xây dựng để hiểu và vận dụng giao thức WebSocket ở tầng ứng dụng.

## Ứng dụng làm được gì

**Đã hoàn thành (MVP):**
- Đăng ký / đăng nhập tài khoản (JWT).
- Trò chuyện theo kênh — tạo kênh mới hoặc tham gia kênh công khai có sẵn.
- Trò chuyện riêng 1-1 (Direct Message).
- Xem lại lịch sử tin nhắn, tải thêm tin cũ hơn khi cuộn lên (phân trang).
- Biết ai đang online theo thời gian thực.

**Dự kiến làm tiếp (xem [Lộ trình](#lộ-trình-phát-triển)):** đang gõ..., đã đọc/chưa đọc, gửi file, tự kết nối lại khi mất mạng, chạy nhiều server bằng Redis Pub/Sub.

## Ý tưởng và nguồn tham khảo

Ý tưởng xuất phát từ [Rocket.Chat](https://github.com/RocketChat/Rocket.Chat) — lấy lại mô hình sản phẩm (channel công khai, direct message, bố cục ba cột) chứ không sao chép mã nguồn. Phần giao thức tham khảo [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455) và [tài liệu WebSocket của MDN](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API); phần backend tham khảo [tài liệu FastAPI](https://fastapi.tiangolo.com/) và [tài liệu MongoDB](https://www.mongodb.com/docs/).

## Tài liệu chi tiết

| Tài liệu | Nội dung |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Sơ đồ kiến trúc, cách quản lý kết nối WebSocket, luồng xác thực và vòng đời một tin nhắn |
| [`docs/protocol.md`](docs/protocol.md) | Đặc tả giao thức WebSocket: handshake, định dạng sự kiện, so sánh với polling/SSE |
| [`docs/data-model.md`](docs/data-model.md) | Thiết kế 3 collection MongoDB và các index |

Dùng ba file này làm nguồn chính khi viết báo cáo — nội dung được viết sẵn ở dạng có thể trích gần như nguyên văn.

## Công nghệ sử dụng

| Thành phần | Lựa chọn |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Giao thức real-time | WebSocket thuần (RFC 6455), không qua Socket.IO |
| Cơ sở dữ liệu | MongoDB |
| Xác thực | JWT, mật khẩu băm bằng bcrypt |
| Frontend | HTML + CSS + JavaScript thuần (dùng trực tiếp WebSocket API của trình duyệt) |

## Cấu trúc thư mục

```
realtime-chat/
├── backend/
│   ├── app/
│   │   ├── main.py        # khởi tạo FastAPI, gắn router, mount frontend
│   │   ├── config.py       # đọc cấu hình từ .env
│   │   ├── db.py            # kết nối MongoDB, tạo index
│   │   ├── security.py     # băm mật khẩu, tạo/giải mã JWT
│   │   ├── deps.py          # dependency xác thực dùng chung cho REST
│   │   ├── serializers.py  # chuyển document Mongo -> JSON trả về client
│   │   ├── api/              # route REST: auth, users, rooms
│   │   └── ws/                # ConnectionManager và endpoint WebSocket
│   ├── tests/               # test viết bằng pytest
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   └── index.html            # toàn bộ giao diện (HTML + CSS + JS trong 1 file)
├── demos/
│   └── echo_server/          # demo WebSocket thuần, tách khỏi FastAPI, để minh họa giao thức
├── docs/
│   ├── architecture.md
│   ├── protocol.md
│   ├── data-model.md
│   ├── screenshots/           # ảnh chụp giao diện/demo để chèn báo cáo
│   └── diagrams/              # sơ đồ (vẽ tay, draw.io, hoặc mermaid)
├── scripts/                   # script tiện ích (sẽ thêm khi cần)
├── .env.example                # mẫu biến môi trường, copy thành .env rồi chỉnh
├── .gitignore
└── CHANGELOG.md
```

## Cài đặt và chạy thử

```bash
# 1. Vào thư mục backend
cd backend

# 2. Tạo virtual environment và cài thư viện
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell)
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt

# 3. (Tùy chọn) tạo file .env từ mẫu nếu muốn đổi cấu hình mặc định
copy ..\.env.example .env         # Windows
# cp ../.env.example .env         # macOS/Linux

# 4. Đảm bảo MongoDB đang chạy (mongodb://localhost:27017), rồi chạy server
uvicorn app.main:app --reload
```

Mở `http://localhost:8000`. Tài liệu API (Swagger) tại `http://localhost:8000/docs`.

## Chạy test

```bash
cd backend
pytest
```

## Lộ trình phát triển

- [x] Chat broadcast cơ bản
- [x] Tài khoản và xác thực (JWT)
- [x] Kênh, chat riêng, lịch sử có phân trang
- [ ] Demo giao thức WebSocket thuần (`demos/echo_server`)
- [ ] Trạng thái "đang gõ...", đã đọc/chưa đọc
- [ ] Tự động kết nối lại khi mất mạng
- [ ] Gửi kèm file/ảnh
- [ ] Chạy nhiều server bằng Redis Pub/Sub
- [ ] Viết test đầy đủ, đóng gói Docker Compose

## Giới hạn hiện tại

- Chỉ chạy được một tiến trình server duy nhất (chưa có Redis Pub/Sub), nên chưa scale ngang được.
- Chưa mã hóa đầu-cuối; khi triển khai thật cần dùng WSS (TLS) để bảo vệ ở tầng vận chuyển.
- Chưa có kênh riêng tư cần lời mời, chỉ có kênh công khai và chat 1-1.
- Đây là đồ án học tập, chưa qua kiểm thử bảo mật ở mức sản phẩm thật.

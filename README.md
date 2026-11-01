# RealChat - Chat thời gian thực bằng WebSocket

Đồ án môn WebSocket. Ứng dụng chat có đăng ký/đăng nhập, chat 1-1, nhóm, gửi ảnh, gọi thoại/video 1-1 và gọi nhóm (WebRTC), chạy trên HTTPS/WSS để nhiều người cùng test qua Internet.

| Thành phần | Công nghệ |
|---|---|
| Backend | Python FastAPI, WebSocket gốc (không Socket.IO), Motor (MongoDB async) |
| CSDL | MongoDB Atlas (free tier) |
| Frontend | HTML/CSS/JS thuần, do chính FastAPI phục vụ (1 service) |
| Gọi thoại/video | WebRTC, WebSocket làm kênh signaling, STUN + TURN |
| Lưu ảnh | Cloudinary, hoặc MongoDB GridFS nếu không cấu hình Cloudinary |
| Xác thực | bcrypt + JWT (REST dùng header, WebSocket dùng `?token=`) |

Tài liệu: [kiến trúc](docs/architecture.md) · [giao thức WebSocket](docs/protocol.md) · [mô hình dữ liệu](docs/data-model.md)

## Tính năng

- Đăng ký, đăng nhập, đăng xuất; mọi người dùng mới tự vào phòng chung `general`.
- Danh sách người dùng online/offline realtime, hỗ trợ nhiều tab.
- Chat 1-1 (không bao giờ tạo trùng phòng cho một cặp), chat nhóm (tạo, thêm/xóa thành viên, rời nhóm).
- Tin nhắn văn bản và hình ảnh (≤ 5MB; jpg/png/gif/webp); lịch sử phân trang cursor, cuộn lên để tải thêm.
- Gọi thoại/video 1-1: popup gọi đến, từ chối, bận, không trả lời sau 30s, tắt/bật mic và camera, cúp máy.
- Gọi nhóm (mesh, tối đa 4 người), vào/ra tùy ý, báo "đã đủ người" khi vượt giới hạn.
- Tự kết nối lại WebSocket (backoff 1s → 15s) + heartbeat ping/pong.
- Số tin chưa đọc (lưu phía client). Giao diện tiếng Việt, dùng được trên điện thoại.

## Chạy local (để phát triển)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy ..\.env.example .env           # rồi điền MONGODB_URI, JWT_SECRET
uvicorn app.main:app --reload
```

Mở `http://localhost:8000` (`localhost` được phép dùng camera/mic dù không có HTTPS). Test: `python -m pytest` (không cần MongoDB, dùng `mongomock-motor`).

## Hướng dẫn deploy từng bước (Render)

### Bước 1. Tạo MongoDB Atlas (free)

1. Đăng ký tại <https://www.mongodb.com/cloud/atlas>, tạo **Project**, rồi **Create** cluster loại **M0 (Free)**.
2. **Database Access** → *Add New Database User*: đặt username + mật khẩu (nên dùng mật khẩu chỉ gồm chữ và số để khỏi phải mã hóa ký tự đặc biệt trong URI).
3. **Network Access** → *Add IP Address* → nhập `0.0.0.0/0` (Allow access from anywhere), vì Render free không có IP cố định.
4. **Database** → *Connect* → *Drivers* → copy chuỗi `mongodb+srv://...`, thay `<password>` bằng mật khẩu thật. Đây là `MONGODB_URI`.

### Bước 2. Lấy TURN miễn phí (Metered Open Relay)

STUN chỉ đủ khi hai người cùng mạng hoặc NAT dễ dãi; khác mạng (4G ↔ WiFi) thường cần TURN để chuyển tiếp media.

1. Đăng ký <https://www.metered.ca/tools/openrelay/> (gói Open Relay miễn phí, có hạn mức dung lượng hàng tháng).
2. Vào Dashboard → **TURN Server** → tạo credential. Ghi lại địa chỉ máy chủ, username, credential.
3. Điền vào:
   - `TURN_URL` = các URL ngăn bằng dấu phẩy, ví dụ `turn:standard.relay.metered.ca:80,turn:standard.relay.metered.ca:443,turns:standard.relay.metered.ca:443?transport=tcp` (lấy đúng giá trị trong dashboard của bạn)
   - `TURN_USERNAME`, `TURN_CREDENTIAL`

Có thể dùng nhà cung cấp TURN khác (Twilio, coturn tự dựng), định dạng biến giống nhau.

### Bước 3. Tạo Cloudinary (tùy chọn)

1. Đăng ký <https://cloudinary.com> (free).
2. Dashboard → copy **Cloud name**, **API Key**, **API Secret** vào `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`.
3. Bỏ qua bước này thì ảnh tự lưu vào MongoDB GridFS (vẫn hoạt động, chỉ tốn dung lượng 512MB của Atlas M0).

### Bước 4. Deploy lên Render

1. Đẩy mã lên GitHub (không commit `.env`).
2. Render → **New** → **Blueprint** → chọn repo; Render đọc [render.yaml](render.yaml) (dùng [Dockerfile](Dockerfile)). Hoặc **New Web Service** → *Runtime: Docker*.
3. Nhập các biến môi trường (xem [.env.example](.env.example)): `MONGODB_URI`, `JWT_SECRET` (blueprint tự sinh), `CLOUDINARY_*`, `TURN_*`, `CORS_ORIGINS` (để trống nếu chỉ dùng chính domain Render).
4. Lệnh khởi động (đã nằm trong Dockerfile): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Nếu dùng Railway/Fly.io: Dockerfile dùng được nguyên xi; hoặc dùng [Procfile](Procfile).
5. Render tự cấp HTTPS, nên WebSocket chạy trên `wss://` và camera/mic hoạt động.

> Gói free của Render tự ngủ sau ~15 phút không có truy cập; lần mở đầu mất khoảng một phút để thức dậy. Hãy mở trang trước giờ demo.

### Bước 5. Kiểm tra sau deploy

1. Mở `https://<tên-app>.onrender.com/healthz` → thấy `{"ok":true}`.
2. Mở trang chính, đăng ký 2 tài khoản trên 2 thiết bị (ví dụ laptop và điện thoại 4G).
3. Gửi tin nhắn, gửi ảnh; kiểm tra chấm xanh online đổi theo thời gian thực.
4. Gọi thoại, gọi video giữa hai thiết bị khác mạng. Nếu bị kẹt "Đang kết nối..." mãi thì thường do thiếu/sai TURN: mở `https://<app>/api/ice-servers` (khi đã đăng nhập, gọi kèm token) để xem có mục `turn:` không, hoặc dùng <https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/> để thử thông tin TURN.
5. Tạo nhóm 3 người rồi gọi nhóm; người thứ 5 vào phải thấy thông báo "đã đủ 4 người".

## Cấu trúc thư mục

```
.
├── Dockerfile, render.yaml, Procfile, .env.example
├── backend/
│   ├── app/            main, config, db, models, security, deps
│   │   ├── api/        auth, users, rooms, files (REST)
│   │   ├── services/   storage (Cloudinary / GridFS)
│   │   └── ws/         manager, calls, endpoint (WebSocket)
│   ├── static/         index.html, css/, js/ (app.js, calls.js)
│   └── tests/          test_auth, test_chat, test_calls
├── docs/               architecture, protocol, data-model
└── demos/echo_server/  (chưa làm) demo WebSocket thuần
```


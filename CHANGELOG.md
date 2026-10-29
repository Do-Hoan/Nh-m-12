# Changelog

## [2.0] - Bản deploy được lên Internet
- Chuyển sang Motor; cấu hình hoàn toàn qua biến môi trường (`.env.example`).
- Nhóm chat (tạo, thêm/xóa thành viên, rời nhóm) thay cho kênh công khai; phòng chung `general` seed sẵn.
- Gửi ảnh (Cloudinary hoặc GridFS), tin nhắn kiểu `image`.
- Gọi thoại/video 1-1 và gọi nhóm (mesh ≤ 4 người) bằng WebRTC, signaling qua WebSocket; ICE có STUN + TURN.
- Heartbeat ping/pong, tự kết nối lại với backoff.
- Giao diện mới (responsive, tiếng Việt), tách `static/{css,js}`; `call_logs`.
- Dockerfile, render.yaml, Procfile, `/healthz`; viết lại tài liệu và test.

## [1.0] - MVP
- Đăng ký/đăng nhập JWT, kênh công khai, DM, lịch sử phân trang, trạng thái online.

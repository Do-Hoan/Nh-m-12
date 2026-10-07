# Kiến trúc hệ thống

## Sơ đồ tổng quan

```
┌─────────────┐        HTTP (REST)         ┌──────────────────┐
│             │  ── đăng nhập, lấy lịch sử ──▶                 │
│   Trình     │                             │    FastAPI       │       ┌──────────┐
│   duyệt     │        WebSocket            │    server        │──────▶│ MongoDB  │
│  (HTML/JS)  │◀── tin nhắn, presence ─────▶│                  │       └──────────┘
└─────────────┘                             └──────────────────┘
```

## Vì sao tách REST và WebSocket

| | REST (HTTP) | WebSocket |
|---|---|---|
| Dùng cho | Đăng ký, đăng nhập, tạo/liệt kê phòng, tải lịch sử tin nhắn | Gửi/nhận tin nhắn mới, cập nhật trạng thái online |
| Đặc điểm | Có trạng thái phản hồi rõ ràng (mã lỗi, phân trang), không cần real-time | Cần hai chiều, cần độ trễ thấp |

Tách riêng hai luồng giúp phần WebSocket chỉ tập trung vào đúng việc cần real-time, đồng thời tận dụng được các cơ chế sẵn có của HTTP (mã trạng thái, cache) cho phần còn lại.

## Quản lý kết nối WebSocket

`ConnectionManager` (`backend/app/ws/manager.py`) giữ một bảng ánh xạ:

```
user_id -> { các WebSocket đang mở của user đó }
```

Một người dùng có thể mở nhiều tab/thiết bị cùng lúc, nên giá trị là một **tập hợp** (set) các kết nối chứ không phải một kết nối duy nhất.

Khi có tin nhắn mới gửi tới một phòng:
1. Server tra `room.members` trong MongoDB để biết ai thuộc phòng đó.
2. Với mỗi `user_id` trong danh sách thành viên, tra trong `ConnectionManager` xem họ có đang mở kết nối nào không.
3. Gửi tin nhắn tới đúng các kết nối đó — **không** broadcast cho tất cả mọi người đang online.

Khi một user mất kết nối hoàn toàn (đóng tab cuối cùng), server phát sự kiện `presence.update` với `status: offline` cho tất cả mọi người.

## Luồng xác thực

1. Người dùng đăng nhập qua `POST /api/auth/login`, nhận về một JWT.
2. Khi mở WebSocket, client gắn token vào query string: `ws://host/ws?token=<JWT>` (trình duyệt không cho gắn header tùy ý khi mở WebSocket, nên không thể dùng `Authorization` header như REST).
3. Server giải mã token ngay sau khi `accept()` kết nối; nếu token sai hoặc hết hạn, server đóng kết nối với mã lỗi tùy chỉnh `4401`.

## Vòng đời một tin nhắn

```
Client gửi message.send qua WebSocket
        │
        ▼
Server kiểm tra: user có thuộc room không?
        │ không → gửi lại error, dừng
        ▼ có
Lưu tin nhắn vào MongoDB (messages collection)
        │
        ▼
Lấy danh sách members của room
        │
        ▼
Gửi sự kiện message.new tới từng kết nối của từng thành viên
```

Nguyên tắc quan trọng: **luôn lưu DB trước rồi mới gửi (broadcast)**. Nếu làm ngược lại, một tin nhắn có thể tới được người nhận nhưng không được lưu nếu server gặp lỗi giữa chừng.

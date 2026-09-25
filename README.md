# RealChat — Ứng dụng chat real-time học WebSocket

> RealChat là một ứng dụng chat nhóm và chat riêng theo thời gian thực, lấy cảm hứng thiết kế từ [Rocket.Chat](https://www.rocket.chat/), được xây dựng để hiểu và vận dụng giao thức WebSocket ở tầng ứng dụng.

## Ứng dụng làm được gì

RealChat cho phép nhiều người dùng nhắn tin với nhau theo thời gian thực trong trình duyệt, không cần tải lại trang.

**Tính năng cốt lõi:**
- Đăng ký và đăng nhập tài khoản.
- Trò chuyện theo kênh (channel) — nhiều người trong một phòng, có thể tạo kênh mới hoặc tham gia kênh công khai có sẵn.
- Trò chuyện riêng 1-1 (Direct Message).
- Xem lại lịch sử tin nhắn của một phòng, tải thêm tin cũ hơn khi cuộn lên.
- Biết ai đang online theo thời gian thực.

## Ý tưởng và nguồn tham khảo

Ý tưởng xuất phát từ [Rocket.Chat](https://github.com/RocketChat/Rocket.Chat) — một nền tảng chat mã nguồn mở được nhiều đội nhóm dùng thay thế Slack. RealChat không sao chép mã nguồn của Rocket.Chat mà chỉ lấy lại **mô hình sản phẩm** của nó để làm đề bài cho môn học:

- Bố cục ba phần quen thuộc: danh sách kênh/người dùng ở cột trái, khung chat ở giữa, trạng thái online hiển thị trực quan — mô phỏng theo cách Rocket.Chat và các ứng dụng chat dạng Slack tổ chức giao diện.
- Khái niệm **channel** (nhóm nhiều người, có thể công khai) và **direct message** (riêng tư giữa hai người) như hai loại phòng chat cơ bản nhất mà hầu hết ứng dụng chat đều có.
- Tài liệu kỹ thuật chính thức của WebSocket ([RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455)) và tài liệu WebSocket của [MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API) được dùng làm nguồn tham khảo cho phần giao thức.
- Tài liệu chính thức của [FastAPI](https://fastapi.tiangolo.com/) (mục WebSockets) và [MongoDB](https://www.mongodb.com/docs/) cho phần triển khai backend.

Phạm vi được thu hẹp lại nhiều so với Rocket.Chat thật (không có admin panel, không có plugin, không có video call...) vì mục tiêu là hiểu sâu WebSocket trong bối cảnh môn học, không phải làm ra một sản phẩm thương mại.

## Vì sao chọn WebSocket

Chat real-time cần server chủ động đẩy tin nhắn mới đến các client đang mở, điều mà HTTP request/response thông thường không làm được. Có ba hướng giải quyết vấn đề này:

| Phương án | Cách hoạt động | Vấn đề |
|---|---|---|
| HTTP polling | Client tự hỏi server liên tục mỗi vài giây | Tốn tài nguyên, tin nhắn đến trễ |
| Long polling | Client gửi request và chờ, server giữ kết nối tới khi có dữ liệu | Vẫn phải mở lại kết nối sau mỗi lần, không hai chiều thật sự |
| **WebSocket** | Bắt tay một lần qua HTTP Upgrade, sau đó duy trì một kết nối TCP hai chiều (full-duplex) | Cần quản lý vòng đời kết nối (mất mạng, đóng kết nối), nhưng đúng bản chất bài toán |

RealChat chọn WebSocket vì đây là phương án phù hợp nhất về mặt kỹ thuật cho chat real-time, đồng thời cũng chính là chủ đề của môn học.

## Kiến trúc xây dựng

```
┌─────────────┐        HTTP (REST)        ┌──────────────────┐
│             │  ── đăng nhập, lấy lịch sử ──▶             │
│   Trình     │                            │    FastAPI      │       ┌──────────┐
│   duyệt     │        WebSocket           │    server       │──────▶│ MongoDB  │
│  (HTML/JS)  │◀── tin nhắn, presence ────▶│                 │       └──────────┘
└─────────────┘                            └──────────────────┘
```

- **REST (HTTP)** phụ trách những gì không cần real-time và cần trạng thái rõ ràng: đăng ký, đăng nhập, tạo/liệt kê phòng, tải lịch sử tin nhắn có phân trang.
- **WebSocket** chỉ phụ trách phần thật sự cần hai chiều theo thời gian thực: gửi/nhận tin nhắn mới, cập nhật trạng thái online.
- Tách hai luồng này giúp phần WebSocket đơn giản, dễ giải thích trong báo cáo, và tận dụng được các thứ có sẵn của HTTP (mã trạng thái, cache, phân trang) cho phần không cần real-time.

Một `ConnectionManager` ở backend giữ ánh xạ `user_id → các kết nối WebSocket đang mở` (một người có thể mở nhiều tab/thiết bị). Khi có tin nhắn mới, server tra bảng thành viên của phòng trong MongoDB rồi chỉ gửi tới đúng những kết nối liên quan, thay vì phát cho tất cả mọi người.

## Công nghệ sử dụng

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Backend             | Python 3.12 + FastAPI            | Hỗ trợ WebSocket sẵn trong framework, lập trình bất đồng bộ (`async/await`), tự sinh tài liệu API |
| Giao thức real-time | WebSocket thuần (chuẩn RFC 6455) | Không qua lớp trừu tượng như Socket.IO, để có thể quan sát và giải thích đúng giao thức trong báo cáo |
| Cơ sở dữ liệu       | MongoDB                          | Lưu trữ dạng tài liệu (document) hợp với dữ liệu chat vốn không cố định cấu trúc; là loại CSDL Rocket.Chat gốc cũng sử dụng |
| Xác thực            | JWT (JSON Web Token)             | Không cần lưu session ở server; token gửi kèm khi mở kết nối WebSocket qua query string |
| Mật khẩu            | bcrypt                           | Thuật toán băm một chiều tiêu chuẩn cho mật khẩu |
| Frontend            | HTML + CSS + JavaScript thuần    | Dùng trực tiếp WebSocket API của trình duyệt, không qua framework, để giữ trọng tâm vào giao thức mạng |

## Giới hạn hiện tại

- Chỉ chạy được một tiến trình server duy nhất (chưa có Redis Pub/Sub), nên chưa scale ngang được.
- Chưa mã hóa đầu-cuối; tin nhắn được bảo vệ ở tầng vận chuyển bằng WSS (TLS) khi triển khai thật, không phải mã hóa nội dung.
- Chưa có kênh riêng tư (private channel) cần lời mời, chỉ có kênh công khai và chat 1-1.
- Đây là đồ án học tập, chưa qua kiểm thử bảo mật ở mức sản phẩm thật.

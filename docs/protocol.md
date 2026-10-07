# Đặc tả giao thức WebSocket

## Bắt tay (handshake)

WebSocket bắt đầu bằng một request HTTP thông thường kèm các header đặc biệt để "nâng cấp" (upgrade) kết nối:

```
GET /ws?token=eyJhbGc... HTTP/1.1
Host: localhost:8000
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
```

Nếu server chấp nhận, nó trả về mã trạng thái `101 Switching Protocols`:

```
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

Sau bước này, kết nối TCP ban đầu được giữ nguyên nhưng không còn là HTTP nữa — cả hai bên có thể gửi dữ liệu cho nhau bất cứ lúc nào, theo cả hai chiều (full-duplex), cho tới khi một bên đóng kết nối.

> Xem thêm: [RFC 6455 — The WebSocket Protocol](https://datatracker.ietf.org/doc/html/rfc6455)

## Endpoint trong dự án

```
ws://host/ws?token=<JWT>
```

Token nằm trong query string vì trình duyệt không cho gắn header tùy ý (`Authorization`) khi mở WebSocket bằng `new WebSocket(url)`.

Mã đóng kết nối tùy chỉnh: `4401` — token sai hoặc hết hạn (dải `4000–4999` được RFC 6455 dành riêng cho ứng dụng tự định nghĩa).

## Định dạng sự kiện

Toàn bộ dữ liệu trao đổi là JSON dạng `{"type": "...", ...}`, mỗi `type` là một loại sự kiện.

### Client → Server

| type | Mô tả | Payload |
|---|---|---|
| `message.send` | Gửi một tin nhắn vào phòng | `room_id`, `content`, `client_id` |

### Server → Client

| type | Mô tả | Payload |
|---|---|---|
| `presence.list` | Gửi ngay sau khi kết nối thành công: danh sách người đang online | `users: string[]` |
| `presence.update` | Một người vừa online/offline | `username`, `status` |
| `message.new` | Có tin nhắn mới trong phòng | `id`, `room_id`, `sender`, `content`, `ts`, `client_id` |
| `error` | Yêu cầu bị từ chối | `code`, `detail` |

Ví dụ một vòng gửi/nhận:

```jsonc
// Client → Server
{ "type": "message.send", "room_id": "66f1...", "content": "Xin chào", "client_id": "abc-123" }

// Server → Client (gửi tới mọi thành viên của phòng, kể cả người gửi)
{
  "type": "message.new",
  "id": "66f2...",
  "room_id": "66f1...",
  "sender": { "id": "66e0...", "username": "ngocduy" },
  "content": "Xin chào",
  "ts": "2026-09-30T10:00:00Z",
  "client_id": "abc-123"
}
```

`client_id` do client tự sinh (ví dụ UUID) và được server gửi trả lại nguyên vẹn trong `message.new`, giúp giao diện nhận ra "đây là tin mình vừa gửi" mà không cần so khớp nội dung.

## So sánh với các phương án khác

| Phương án | Độ trễ | Chi phí tài nguyên | Hai chiều thật sự |
|---|---|---|---|
| HTTP polling (hỏi lại mỗi vài giây) | Cao | Cao (nhiều request thừa) | Không |
| Long polling (giữ request tới khi có dữ liệu) | Trung bình | Trung bình | Không hẳn (vẫn phải mở lại sau mỗi lần) |
| Server-Sent Events (SSE) | Thấp | Thấp | Không (chỉ một chiều server → client) |
| **WebSocket** | Thấp | Thấp | Có |

## Cách quan sát giao thức để chụp cho báo cáo

1. Chạy ứng dụng, mở DevTools (F12) → tab **Network** → lọc **WS**.
2. Mở `http://localhost:8000`, đăng nhập — sẽ thấy một kết nối tới `/ws?token=...` xuất hiện trong danh sách.
3. Bấm vào kết nối đó → tab **Messages** để xem từng frame JSON gửi/nhận theo thời gian thực — đây là phần nên chụp màn hình cho báo cáo.
4. Xem phần header của request bằng tab **Headers** để thấy `Upgrade: websocket`, `Sec-WebSocket-Key`, mã phản hồi `101`.

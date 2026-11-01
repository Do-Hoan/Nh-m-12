# Đặc tả giao thức WebSocket

Một endpoint duy nhất: `ws(s)://<host>/ws?token=<JWT>`. Toàn bộ dữ liệu là JSON dạng `{"type": "...", ...}`.

- Trang chạy HTTPS thì dùng `wss://` (frontend tự chọn theo `location.protocol`).
- Token nằm trên query string vì trình duyệt không cho gắn header `Authorization` khi mở WebSocket.
- Mã đóng tùy chỉnh: `4401` = token sai/hết hạn. Client gặp mã này thì đăng xuất, không tự kết nối lại.
- Mỗi khung (frame) tối đa 128 KB; vượt quá nhận `error TOO_LARGE`.

## 1. Kết nối, presence, heartbeat

| Hướng | type | Trường | Ý nghĩa |
|---|---|---|---|
| S→C | `presence.list` | `users: [user_id]` | Gửi ngay sau khi kết nối: ai đang online |
| S→C | `presence.update` | `user_id`, `username`, `status: online\|offline` | Chỉ phát khi user mở tab ĐẦU TIÊN / đóng tab CUỐI CÙNG (hỗ trợ nhiều tab) |
| S→C | `user.created` | `user: {id, username}` | Có người mới đăng ký, cập nhật danh sách |
| C→S | `ping` | – | Heartbeat, client gửi mỗi 20 giây |
| S→C | `pong` | – | Client 10 giây không thấy pong thì đóng và tự kết nối lại |

Server cũng tự đóng kết nối nếu 60 giây không nhận được gì (kể cả ping). Client tự kết nối lại với backoff tăng dần 1s, 2s, 4s, 8s... tối đa 15s.

## 2. Tin nhắn

```jsonc
// C→S  gửi tin
{ "type": "message.send", "room_id": "...", "msg_type": "text",  "content": "Xin chào", "client_id": "abc" }
{ "type": "message.send", "room_id": "...", "msg_type": "image", "content": "https://res.cloudinary.com/.../a.jpg", "client_id": "abd" }

// S→C  tới MỌI thành viên đang online của phòng (kể cả người gửi, mọi tab)
{ "type": "message.new", "id": "...", "room_id": "...", "sender": {"id": "...", "username": "an"},
  "msg_type": "text", "content": "Xin chào", "ts": "2026-10-30T10:00:00Z", "client_id": "abc" }
```

Server xử lý theo đúng thứ tự: **(1) kiểm tra người gửi thuộc phòng → (2) lưu MongoDB → (3) mới broadcast**. Tin ảnh chỉ chấp nhận URL do chính hệ thống cấp (Cloudinary của mình hoặc `/api/files/...`), không nhận URL tùy ý.

Ảnh được gửi bằng 2 bước: `POST /api/upload` (multipart, tối đa 5MB, jpg/png/gif/webp, kiểm tra cả "magic bytes") → nhận `{"url"}` → gửi `message.send` với `msg_type: image`.

## 2.1. Chỉ báo đang gõ (Typing Indicator)

Dùng để thông báo một thành viên đang nhập tin nhắn trong phòng chat.

| Hướng | type | Trường | Ý nghĩa |
|---|---|---|---|
| C→S | `typing.start` | `room_id` | Bắt đầu nhập tin nhắn |
| C→S | `typing.stop` | `room_id` | Dừng nhập tin nhắn |
| S→C | `typing.start` | `room_id`, `user_id`, `username` | Thông báo người dùng đang gõ |
| S→C | `typing.stop` | `room_id`, `user_id`, `username` | Thông báo người dùng đã dừng gõ |

**Ví dụ Client → Server**

Bắt đầu nhập:

```json
{
  "type": "typing.start",
  "room_id": "ROOM_ID"
}
```

Dừng nhập:

```json
{
  "type": "typing.stop",
  "room_id": "ROOM_ID"
}
```

**Ví dụ Server → Client**

```json
{
  "type": "typing.start",
  "room_id": "ROOM_ID",
  "user_id": "USER_ID",
  "username": "an"
}
```

Server chỉ gửi sự kiện cho các thành viên trong phòng hợp lệ.

Typing Indicator chỉ là trạng thái tạm thời, không lưu vào MongoDB.

## 2.2. Đánh dấu tin nhắn đã đọc (Message Read)

Dùng để lưu trạng thái đọc tin nhắn vào MongoDB và đồng bộ cho các thành viên trong phòng.

| Hướng | type | Trường | Ý nghĩa |
|---|---|---|---|
| C→S | `message.read` | `room_id`, `message_id` (tùy chọn) | Đánh dấu tin nhắn đã đọc |
| S→C | `message.read` | `room_id`, `user_id`, `read_at` | Thông báo trạng thái đã đọc |

**Ví dụ Client → Server**

```json
{
  "type": "message.read",
  "room_id": "ROOM_ID",
  "message_id": "MESSAGE_ID"
}
```

**Ví dụ Server → Client**

```json
{
  "type": "message.read",
  "room_id": "ROOM_ID",
  "user_id": "USER_ID",
  "read_at": "2026-10-30T10:00:00"
}
```

Dữ liệu được lưu trong MongoDB:

- `messages.read_by`: danh sách người đã đọc tin nhắn.
- `rooms.read_by`: lưu thời gian đọc gần nhất của từng thành viên.

Trạng thái đọc được gửi qua WebSocket để các thiết bị đang kết nối cập nhật.

## 2.3. Chỉnh sửa tin nhắn (Message Edit)

Dùng để chỉnh sửa nội dung tin nhắn đã gửi.

| Hướng | type | Trường | Ý nghĩa |
|---|---|---|---|
| C→S | `message.edit` | `room_id`, `message_id`, `content` | Yêu cầu chỉnh sửa tin nhắn |
| S→C | `message.edited` | Thông tin tin nhắn đã cập nhật | Thông báo tin nhắn được chỉnh sửa |

**Ví dụ Client → Server**

```json
{
  "type": "message.edit",
  "room_id": "ROOM_ID",
  "message_id": "MESSAGE_ID",
  "content": "Nội dung mới"
}
```

**Ví dụ Server → Client**

```json
{
  "type": "message.edited",
  "id": "MESSAGE_ID",
  "room_id": "ROOM_ID",
  "content": "Nội dung mới",
  "edited_at": "2026-10-30T10:00:00"
}
```

Quy tắc:

- Chỉ người gửi mới được chỉnh sửa tin nhắn.
- Nội dung không được để trống.
- Nội dung không vượt quá giới hạn `MAX_MESSAGE_LEN`.
- Server lưu nội dung mới và thời gian chỉnh sửa vào MongoDB.
- Server broadcast sự kiện `message.edited` đến các thành viên trong phòng.

## 2.4. Thu hồi tin nhắn (Message Delete)

Dùng để thu hồi tin nhắn đã gửi.

| Hướng | type | Trường | Ý nghĩa |
|---|---|---|---|
| C→S | `message.delete` | `room_id`, `message_id` | Yêu cầu thu hồi tin nhắn |
| S→C | `message.deleted` | Thông tin tin nhắn đã thu hồi, `message_id` | Thông báo tin nhắn đã bị thu hồi |

**Ví dụ Client → Server**

```json
{
  "type": "message.delete",
  "room_id": "ROOM_ID",
  "message_id": "MESSAGE_ID"
}
```

**Ví dụ Server → Client**

```json
{
  "type": "message.deleted",
  "message_id": "MESSAGE_ID",
  "content": "[tin nhắn đã thu hồi]"
}
```

Quy tắc:

- Chỉ người gửi mới được thu hồi tin nhắn.
- Tin nhắn được đánh dấu bằng `deleted_at` trong MongoDB.
- Nội dung được thay bằng `[tin nhắn đã thu hồi]`.
- Server broadcast sự kiện `message.deleted` đến các thành viên trong phòng.

Đây là cơ chế thu hồi mềm (Soft Delete), không xóa bản ghi khỏi MongoDB.

## 2.5. Biểu tượng cảm xúc (Message Reaction)

Dùng để thêm hoặc gỡ biểu tượng cảm xúc trên tin nhắn.

| Hướng | type | Trường | Ý nghĩa |
|---|---|---|---|
| C→S | `message.reaction` | `room_id`, `message_id`, `emoji` | Thêm hoặc gỡ reaction |
| S→C | `message.reaction` | Thông tin tin nhắn đã cập nhật, `emoji` | Đồng bộ reaction |

**Ví dụ Client → Server**

```json
{
  "type": "message.reaction",
  "room_id": "ROOM_ID",
  "message_id": "MESSAGE_ID",
  "emoji": "❤️"
}
```

**Ví dụ Server → Client**

```json
{
  "type": "message.reaction",
  "message_id": "MESSAGE_ID",
  "emoji": "❤️"
}
```

Quy tắc:

- Mỗi người dùng có thể thêm reaction vào tin nhắn.
- Nếu người dùng đã thả cùng emoji thì gửi lại sự kiện sẽ gỡ reaction đó.
- Reaction được lưu trong MongoDB tại trường `reactions`.
- Server broadcast thay đổi đến các thành viên trong phòng.

## 2.6. Kiểm tra quyền và xử lý lỗi

Server phải kiểm tra người dùng thuộc phòng trước khi thực hiện các thao tác theo phòng.

Các lỗi có thể trả về:

| code | Ý nghĩa |
|---|---|
| `FORBIDDEN` | Người dùng không thuộc phòng hoặc không có quyền thao tác |
| `NOT_FOUND` | Không tìm thấy tin nhắn |
| `INVALID_CONTENT` | Nội dung hoặc emoji không hợp lệ |
| `INTERNAL` | Lỗi máy chủ |

## 3. Nhóm

| Hướng | type | Trường | Khi nào |
|---|---|---|---|
| S→C | `group.created` | `room` | Bạn vừa được tạo nhóm / được thêm vào nhóm |
| S→C | `group.updated` | `room` | Thành viên hoặc người tạo nhóm thay đổi |
| S→C | `group.removed` | `room_id` | Bạn bị xóa khỏi nhóm hoặc vừa rời nhóm |

Tạo nhóm, thêm/xóa thành viên, rời nhóm đi qua REST (`/api/rooms/...`); server đẩy các sự kiện trên để mọi client đang online cập nhật ngay.

## 4. Cuộc gọi (signaling)

WebSocket chỉ làm kênh **signaling**; âm thanh/hình ảnh đi trực tiếp giữa các trình duyệt qua WebRTC (STUN/TURN khi cần). Gọi 1-1 và gọi nhóm dùng chung một bộ message.

### Client → Server

| type | Trường | Ý nghĩa |
|---|---|---|
| `call.invite` | `room_id`, `media: audio\|video` | Bắt đầu gọi (DM: gọi người kia; nhóm: gọi cả nhóm) |
| `call.accept` | `call_id` | Nghe máy / tham gia cuộc gọi nhóm đang diễn ra |
| `call.reject` | `call_id` | Từ chối khi đang đổ chuông |
| `call.end` | `call_id` | Cúp máy / rời cuộc gọi / hủy khi chưa ai nghe |
| `webrtc.offer` | `call_id`, `to: user_id`, `payload: {sdp}` | SDP offer |
| `webrtc.answer` | `call_id`, `to`, `payload: {sdp}` | SDP answer |
| `webrtc.ice` | `call_id`, `to`, `payload: {candidate}` | ICE candidate |

### Server → Client

| type | Trường | Gửi cho | Ý nghĩa |
|---|---|---|---|
| `call.ringing` | `call_id`, `room_id`, `media`, `is_group` | Người gọi | Đã tạo cuộc gọi, đang đổ chuông |
| `call.incoming` | `call_id`, `room_id`, `room_name`, `media`, `is_group`, `from` | Người được gọi (mọi tab) | Hiện popup nhận/từ chối |
| `call.busy` | `room_id`, `reason` | Người gọi | Người kia đang bận |
| `call.unavailable` | `room_id`, `reason: offline` | Người gọi | Người kia không online |
| `call.joined` | `call_id`, `participants: [user]`, ... | Người vừa vào | Danh sách người đang ở trong cuộc gọi → tạo offer tới từng người |
| `call.participant_joined` | `call_id`, `user` | Người đã ở trong | Có người mới, chờ nhận offer |
| `call.participant_left` | `call_id`, `user` | Người còn lại | Có người rời |
| `call.rejected` | `call_id`, `user` | Người đang ở trong | Có người từ chối |
| `call.dismiss` | `call_id`, `reason: timeout\|cancelled\|handled\|rejected` | Người đang đổ chuông | Đóng popup (nhỡ / bị hủy / tab khác đã nghe) |
| `call.ended` | `call_id`, `room_id`, `reason: ended\|rejected\|timeout\|cancelled` | Người đang ở trong | Cuộc gọi kết thúc |
| `call.status` | `room_id`, `call_id\|null`, `media`, `participants` | Cả phòng nhóm | Nhóm đang có cuộc gọi → hiện nút "Tham gia" |
| `webrtc.offer/answer/ice` | `call_id`, `from: user_id`, `payload` | Người nhận | Server chỉ chuyển tiếp, không đọc nội dung |
| `error` | `code`, `detail` | Người gửi | Xem mục 5 |

### Sơ đồ gọi 1-1 (A gọi B)

```
  A (người gọi)                Server                      B (người nghe)
      | call.invite ------------> |                              |
      | <------------ call.ringing|-------- call.incoming ------>|   (popup)
      |                           |  [bắt đầu đếm 30 giây]       |
      |                           | <----------- call.accept ----|
      | <- call.participant_joined|---- call.joined [A] ------->|
      |                           | <--------- webrtc.offer (to A)|  B tạo offer
      | <------- webrtc.offer ----|                              |
      | webrtc.answer (to B) ---> |------- webrtc.answer ------->|
      | <=== webrtc.ice ===========(hai chiều)=== webrtc.ice ===>|
      |<================ media P2P (STUN/TURN) =================>|
      | call.end ---------------> |------- call.ended ---------->|   (cúp máy)
```

Các nhánh khác:

```
 B không trả lời 30s : Server -> B  call.dismiss(timeout) ; Server -> A  call.ended(timeout)
 B từ chối           : B -> call.reject ; A nhận call.rejected rồi call.ended(rejected)
 A hủy khi đang đổ chuông : A -> call.end ; B nhận call.dismiss(cancelled)
 B bận (đang gọi khác)    : A nhận call.busy ngay, B không bị làm phiền
 B offline                : A nhận call.unavailable
 B mở nhiều tab           : tất cả tab đều đổ chuông; tab nào nghe thì tab còn lại nhận call.dismiss(handled)
 Mất kết nối WebSocket    : server coi như cúp máy, người còn lại nhận call.participant_left / call.ended
```

### Gọi nhóm (mesh, tối đa 4 người)

```
 A call.invite(room nhóm) -> các thành viên online & rảnh nhận call.incoming (is_group=true)
 B call.accept -> B nhận call.joined [A]    -> B offer A
 C call.accept -> C nhận call.joined [A, B] -> C offer A, C offer B
 D call.accept -> D offer A, B, C          (mỗi cặp một RTCPeerConnection)
 E call.accept -> error CALL_FULL "Cuộc gọi đã đủ 4 người"
 Người vào sau (qua nút "Tham gia" nhờ call.status) cũng dùng call.accept.
 Ai cúp máy: call.end -> người còn lại nhận call.participant_left.
 Cuộc gọi kết thúc khi còn <= 1 người và không còn ai đang đổ chuông.
```

Quy ước: **người mới vào chủ động tạo offer tới mọi người đã ở trong cuộc gọi**, nên không bao giờ xảy ra hai bên cùng offer (glare).

## 5. Mã lỗi (`error`)

| code | Ý nghĩa |
|---|---|
| `BAD_REQUEST` | Không phải JSON hoặc thiếu `type` |
| `UNKNOWN_TYPE` | `type` không được hỗ trợ |
| `FORBIDDEN` | Không thuộc phòng |
| `INVALID_CONTENT` | Nội dung rỗng/quá dài, `msg_type` sai, URL ảnh không hợp lệ |
| `ALREADY_IN_CALL` | Bạn đang ở trong cuộc gọi khác |
| `CALL_EXISTS` | Phòng đã có cuộc gọi (kèm `call_id`), hãy tham gia |
| `CALL_FULL` | Cuộc gọi đã đủ người |
| `NO_CALL` | Cuộc gọi không còn / không có quyền |
| `TOO_LARGE` | Dữ liệu quá lớn |
| `INTERNAL` | Lỗi máy chủ |

## 6. Quan sát giao thức (để chụp báo cáo)

DevTools (F12) → Network → lọc **WS** → bấm kết nối `/ws` → tab **Messages** để xem từng frame JSON; tab **Headers** có `Upgrade: websocket`, `Sec-WebSocket-Key` và phản hồi `101 Switching Protocols`.

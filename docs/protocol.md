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

# Mô hình dữ liệu MongoDB

Database: `chatapp` (đổi bằng biến môi trường `DB_NAME`). Collection: `users`, `rooms`, `messages`, `call_logs` (và `fs.files`/`fs.chunks` của GridFS nếu không dùng Cloudinary).

## `users`

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `_id` | ObjectId | |
| `username` | string | Duy nhất (unique index), 3-20 ký tự: chữ, số, `_` |
| `password_hash` | string | bcrypt, không bao giờ lưu mật khẩu thô |
| `created_at` | datetime (UTC) | |

## `rooms`

Một collection cho cả chat riêng và nhóm, phân biệt bằng `type`.

```jsonc
// Nhóm
{ "_id": ObjectId, "type": "group", "name": "Nhóm học", "members": [ObjectId, ...],
  "created_by": ObjectId, "created_at": ISODate }

// Phòng chung mặc định: giống nhóm nhưng có cờ is_default, created_by = null.
// Mọi người dùng mới được tự thêm vào; không ai rời được, không ai bị xóa.
{ "type": "group", "name": "general", "is_default": true, "members": [...], "created_by": null }

// Chat 1-1
{ "_id": ObjectId, "type": "dm", "dm_key": "66e0...:66e1...", "members": [ObjectId, ObjectId],
  "created_by": ObjectId, "created_at": ISODate }
```

`dm_key` là hai `user_id` sắp xếp theo thứ tự chữ cái, nối bằng `:`. Kết hợp **unique index (partial)** và `find_one_and_update(upsert=True)` (atomic) nên mỗi cặp người chỉ có đúng một phòng DM, kể cả khi hai người bấm "nhắn tin" cùng lúc.

Quy tắc nhóm: chỉ `created_by` thêm/xóa thành viên; ai cũng rời được (trừ `general`); người tạo rời thì quyền chuyển cho thành viên kế tiếp; người cuối cùng rời thì nhóm và tin nhắn bị xóa.

## `messages`

```jsonc
{ "_id": ObjectId, "room_id": ObjectId, "sender_id": ObjectId, "sender_name": "an",
  "type": "text",            // "text" | "image"
  "content": "Xin chào",     // text: nội dung; image: URL ảnh
  "created_at": ISODate }
```

`sender_name` lưu lặp (denormalize) để đọc lịch sử chỉ cần một truy vấn, không phải join sang `users`.

## `call_logs`

Ghi một bản ghi khi cuộc gọi kết thúc.

```jsonc
{ "call_id": "hex", "room_id": ObjectId, "type": "dm|group", "media": "audio|video",
  "initiator_id": ObjectId, "participants": [ObjectId, ...],
  "started_at": ISODate, "answered_at": ISODate|null, "ended_at": ISODate,
  "duration_s": 0, "status": "answered|rejected|timeout|cancelled" }
```

## Index (xem `backend/app/db.py`)

| Collection | Index | Mục đích |
|---|---|---|
| `users` | `username` (unique) | Không trùng tên đăng nhập |
| `rooms` | `members` | Tìm các phòng của một user |
| `rooms` | `dm_key` (unique, partial) | Không trùng phòng DM |
| `messages` | `(room_id, created_at desc)` | Lịch sử tin nhắn theo phòng và thời gian |
| `messages` | `(room_id, _id desc)` | Phân trang theo cursor |
| `call_logs` | `(room_id, started_at desc)` | Tra lịch sử gọi |

## Phân trang bằng cursor

`GET /api/rooms/{id}/messages?limit=30&before=<message_id>` trả tối đa `limit` tin có `_id < before`, mới nhất trước rồi đảo lại thành cũ → mới. `ObjectId` có 4 byte đầu là timestamp nên tăng dần theo thời gian tạo; dùng làm cursor tránh được lỗi trùng giờ và không bị lệch khi có tin mới chen vào (khác với `skip/offset`).

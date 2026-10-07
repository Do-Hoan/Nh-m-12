# Mô hình dữ liệu MongoDB

Database: `chatapp` (đổi được qua biến môi trường `DB_NAME`). Gồm 3 collection.

## `users`

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `_id` | ObjectId | Khóa chính, tự sinh |
| `username` | string | Duy nhất (unique index), 3–20 ký tự, chỉ gồm chữ/số/`_` |
| `password_hash` | string | Băm bằng bcrypt, không bao giờ lưu plaintext |
| `created_at` | datetime (UTC) | |

## `rooms`

Dùng chung cho cả kênh (channel) và chat riêng (DM) bằng trường `type`.

**Kênh:**
```json
{
  "_id": ObjectId,
  "type": "channel",
  "name": "general",
  "members": [ObjectId, ObjectId, ...],
  "owner_id": ObjectId,
  "created_at": ISODate
}
```

**Chat riêng (DM):**
```json
{
  "_id": ObjectId,
  "type": "dm",
  "dm_key": "66e0...:66e1...",
  "members": [ObjectId, ObjectId],
  "created_at": ISODate
}
```

`dm_key` là chuỗi ghép hai `user_id` theo thứ tự alphabet (`sorted()`), dùng làm unique index để đảm bảo **mỗi cặp người dùng chỉ có đúng một phòng DM**, kể cả khi họ bấm "nhắn tin" nhiều lần.

## `messages`

```json
{
  "_id": ObjectId,
  "room_id": ObjectId,
  "sender_id": ObjectId,
  "sender_name": "ngocduy",
  "content": "Xin chào",
  "created_at": ISODate
}
```

`sender_name` được lưu lặp lại (denormalize) thay vì chỉ lưu `sender_id` rồi join sang `users`, để đọc lịch sử tin nhắn chỉ cần một truy vấn, không cần tra cứu thêm — đánh đổi hợp lý vì tên người dùng hiếm khi đổi.

## Index đã tạo (xem `backend/app/db.py`)

| Collection | Index | Mục đích |
|---|---|---|
| `users` | `username` (unique) | Không cho trùng tên đăng nhập |
| `rooms` | `members` | Tra nhanh "các phòng mà user X tham gia" |
| `rooms` | `dm_key` (unique, partial) | Đảm bảo không trùng phòng DM |
| `rooms` | `name` (unique, partial, chỉ áp dụng `type: channel`) | Không trùng tên kênh |
| `messages` | `(room_id, _id desc)` | Phân trang lịch sử: lọc theo phòng, sắp theo thời gian tạo |

## Vì sao dùng `_id` để phân trang thay vì trường thời gian riêng

`ObjectId` của MongoDB có 4 byte đầu là timestamp, nên tự nhiên tăng dần theo thời gian tạo. Dùng `_id` làm cursor (`{"_id": {"$lt": last_id}}`) vừa chính xác (không bị trùng giờ như nhiều tin gửi cùng giây), vừa không cần thêm trường hay index phụ.

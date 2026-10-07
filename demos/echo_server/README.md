# Demo: Echo server bằng WebSocket thuần

Mục đích: minh họa giao thức WebSocket ở mức thấp nhất, không qua FastAPI, để
phục vụ phần giải thích giao thức trong báo cáo (xem `docs/protocol.md`).

Chưa viết — dự kiến gồm:
- `server.py`: dùng thư viện `websockets`, nhận một tin nhắn và gửi lại y nguyên (echo)
- `client.html`: trang HTML đơn giản để gửi tin thử bằng tay

Chạy dự kiến:
```bash
pip install websockets
python server.py
# rồi mở client.html bằng trình duyệt
```

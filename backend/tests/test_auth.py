"""
Khung test cho phần đăng ký/đăng nhập.
Chạy bằng: pytest (ở trong thư mục backend/, sau khi kích hoạt virtual environment)

TODO (sẽ hoàn thiện ở giai đoạn kiểm thử):
- Đăng ký thành công trả về access_token
- Đăng ký trùng username -> lỗi 409
- Đăng nhập sai mật khẩu -> lỗi 401
- Gọi /api/auth/me không kèm token -> lỗi 401
"""
import pytest


@pytest.mark.skip(reason="Chưa viết - sẽ hoàn thiện ở Giai đoạn kiểm thử")
def test_register_success():
    pass

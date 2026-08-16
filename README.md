# Neko MultiPK

## Cấu trúc dữ liệu
- `state.idols` là nguồn dữ liệu Idol duy nhất.
- MultiPK chỉ chọn `idol_id` từ danh sách Idol ở **phần quản lý MultiPK**.
- Bảng Rank chỉ hiển thị dữ liệu, **không có nút chọn thành viên PK**.
- PK tự đồng bộ tên / TikTok ID / avatar từ record Idol được chọn.
- Điểm PK cộng vào `idol.score`, nên Rank và PK dùng chung điểm Idol.

## MultiPK
- 3 / 4 / 5 người.
- Chọn thành viên trực tiếp tại từng `Vị trí` trong phần quản lý PK.
- Mỗi vị trí có `gift_id` kích hoạt và `gift_img`.
- Một phòng TikTok Live duy nhất.
- User gửi gift_id kích hoạt -> chọn/chuyển phe; chính gift đó vẫn tính điểm.
- Các gift tiếp theo của user -> tính cho phe hiện tại.
- Gửi gift_id kích hoạt khác -> chuyển sang vị trí mới.

## Chức năng Idol
- Tìm kiếm Idol.
- Thêm một Idol.
- Thêm hàng loạt bằng xuống dòng.
- TikTok ID có thể tự lấy avatar.

## Chạy
```bash
pip install -r requirements.txt
python server.py
```

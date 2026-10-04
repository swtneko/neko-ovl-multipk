# Neko Overlay · Multi-PK

Overlay **PK 2 đến 5 người** cho TikTok Live, chạy ngay trên máy bạn, **không cần đăng nhập** tài khoản nào. Chỉ dùng **một phòng live**, người xem tự chọn phe bằng một món quà "kích hoạt".

---

## 1. Cài đặt (Windows)

### Bước 1: Cài Python (chỉ làm một lần)

Tải Python 3.10 trở lên tại https://www.python.org/downloads/ rồi cài đặt.
**Quan trọng:** ở màn hình cài đặt đầu tiên, tick vào ô **"Add python.exe to PATH"**.

### Bước 2: Tải code về

1. Vào trang GitHub của dự án, bấm nút xanh **Code** → **Download ZIP**.
2. Giải nén file ZIP ra một thư mục, ví dụ `D:\neko-ovl-multipk`.

### Bước 3: Mở CMD trong thư mục vừa giải nén

Mở thư mục đó trong File Explorer (thấy các file `server.py`, `requirements.txt`, thư mục `static`), bấm vào **thanh địa chỉ** phía trên, gõ `cmd` rồi nhấn **Enter**. CMD sẽ mở sẵn đúng thư mục.

### Bước 4: Cài thư viện và chạy

```bat
pip install -r requirements.txt
python server.py
```

Thấy dòng `Uvicorn running on http://0.0.0.0:8000` là server đã chạy. **Giữ nguyên cửa sổ CMD này**, tắt cửa sổ là tắt server.

Mở trình duyệt, vào http://localhost:8000/control để bắt đầu dùng.

### Những lần chạy sau

Mở CMD trong thư mục (Bước 3) rồi gõ:

```bat
python server.py
```

Muốn dừng server: bấm `Ctrl + C` trong cửa sổ CMD.

> Muốn đổi cổng 8000: `set PORT=9000` rồi `python server.py`.
> Dùng từ máy khác trong mạng LAN (điện thoại, máy OBS riêng): thay `localhost` bằng IP của máy chạy server, ví dụ `http://192.168.1.10:8000/control`.

---

## 2. Cách PK hoạt động

- Mỗi **vị trí** PK (2 đến 5 vị trí) gắn với **một idol** và **một gift kích hoạt**.
- Người xem **gửi gift kích hoạt** của vị trí nào thì được xếp vào phe đó. Chính món quà này **cũng được tính điểm** cho phe vừa chọn.
- Sau khi đã chọn phe, **mọi quà khác** người đó gửi (loại nào cũng được) đều cộng cho phe đó.
- Muốn đổi phe thì gửi gift kích hoạt của phe khác.
- Người xem **chưa chọn phe** gửi quà thường thì **không được tính**.

Dưới mỗi vị trí trên overlay có hiện icon gift kích hoạt, để người xem biết cần gửi quà nào.

---

## 3. Sử dụng

### Các địa chỉ

| Địa chỉ | Dùng để |
|---|---|
| `http://localhost:8000/control` | Bảng điều khiển |
| `http://localhost:8000/overlay/pk` | Thanh PK (OBS) |
| `http://localhost:8000/overlay/rank` | Bảng xếp hạng tổng điểm các idol (OBS) |

Link cho OBS nằm ở mục **OBS Browser Source** trong control. Bấm vào link để copy.

### Các bước chạy một hiệp PK

**1. Thêm idol** (khối "THÊM IDOL", cột trái). Đây là danh sách chung để chọn người vào PK.
- Tab **Thêm 1**: nhập tên, TikTok ID (bấm **🔍 Kiểm tra avatar** để tự lấy ảnh) hoặc dán link ảnh avatar.
- Tab **Hàng loạt**: mỗi dòng một idol, dạng `Tên`, `Tên | @tiktok_id` hoặc `@tiktok_id`. Avatar tự lấy khi thêm (nhiều idol thì hơi lâu).
- Tab **Import/Export**: mỗi dòng `tên|username|điểm|link avatar` (username và link avatar có thể bỏ trống). **Export** xuất danh sách ra ô văn bản để bạn copy lưu lại.
- **🔄 Tìm avatar còn thiếu** gán avatar cho các idol đã có TikTok ID mà chưa có ảnh.

**2. Cấu hình PK** (khối "⚔️ MultiPK")
- Chọn **số người** (2 đến 5).
- Mỗi vị trí: chọn **idol** trong danh sách (không được chọn một idol cho hai vị trí), rồi bấm **🎁 Chọn gift kích hoạt**, tìm theo tên quà hoặc ID (có sẵn 643 quà). Mỗi vị trí phải dùng **một gift khác nhau**.
- Bấm **💾 Lưu cấu hình**.

> Nên chọn quà nhỏ, dễ gửi làm gift kích hoạt, để người xem chọn phe thoải mái.

**3. Kết nối TikTok**: ô cuối cột phải ("📡 TikTok Live"), nhập username phòng live (không cần `@`), bấm **Kết nối**. Chờ hiện `✔ Đã kết nối`. **Bắt buộc phải nối xong thì mới bấm Bắt đầu được.** Phòng phải đang live.

**4. Đặt thời gian**: khối "⏱ Đếm thời gian", nhập phút và giây, bấm **Đặt thời gian**.

**5. Mở overlay trong OBS**: thêm **Browser Source**, dán link `/overlay/pk`. Nền trong suốt sẵn. Widget tự căn giữa khung, gợi ý khung khoảng **900 × 300**, chỉnh lại nếu bị cắt.

**6. Bắt đầu**: bấm **▶ Bắt đầu**. Nếu thiếu gì (chưa chọn idol, chưa chọn gift, chưa nối TikTok) sẽ có thông báo cho biết thiếu ở vị trí nào.

### Trong hiệp

| Muốn làm | Cách làm |
|---|---|
| Xem ai đang ở phe nào | Danh sách "🎯 User đã được chọn vị trí" ở khối TikTok Live |
| Sửa điểm một phe | Ở từng vị trí: **+100 / +500 / +1000 / -100** hoặc ô **± điểm** + **Cộng** |
| Kết thúc ngay | **⏹ Kết thúc** |
| Đưa về ban đầu | **🔄 Reset** (điểm PK về 0, đồng hồ về đầu) |

Trên overlay: `Stand by` khi chưa chạy, đếm ngược `mm:ss` khi đang chạy, `Finish` khi xong. Người dẫn đầu hiện nhãn `No.1`.

### Hiệp tiếp theo

Bấm **Đặt thời gian** (có thể giữ nguyên số phút) để mở **hiệp mới**: điểm PK về 0, danh sách người xem đã chọn phe được xoá. Sau đó bấm **▶ Bắt đầu**.
Nếu bấm Bắt đầu mà **không** Đặt thời gian trước, điểm PK của hiệp trước vẫn còn và sẽ cộng dồn tiếp.

### Cài đặt nâng cao (khối "⚙️ Cài đặt PK nâng cao")

- **🌫️ Sương mù**: che thanh điểm để người xem không biết ai đang dẫn. Bấm **Bật sương mù**, ô **Bật khi còn N giây**: `0` là che ngay từ đầu hiệp, `30` là che khi đồng hồ còn 30 giây. Bấm **Lưu** sau khi đổi số. Sương mù tự tan khi vào giai đoạn thống kê cuối và khi hiệp kết thúc.
- **⏳ Thống kê cuối hiệp**: số giây (mặc định 5) vẫn nhận quà sau khi đồng hồ về 0, để không mất quà gửi vào những giây cuối. Đặt `0` để tắt. Bấm **Lưu**.

### Bảng xếp hạng (`/overlay/rank`)

Hiển thị **tổng điểm tích luỹ** của tất cả idol, idol đang ở trong PK được tô màu theo vị trí. Điểm ở đây cộng dồn qua mọi hiệp, **không** về 0 khi sang hiệp mới.

Có thể chỉnh bằng cách thêm vào cuối link, ví dụ `/overlay/rank?order=row&perCol=10&from=1&to=20`:
`order` = `row` (ngang) hoặc `col` (dọc), `perCol` = số idol mỗi cột, `from` / `to` = hiện từ hạng nào đến hạng nào.

---

## 4. Lưu ý quan trọng

- **Tạm dừng rồi Bắt đầu lại sẽ xoá danh sách người đã chọn phe.** Người xem phải gửi lại gift kích hoạt mới được tính tiếp (điểm và đồng hồ vẫn giữ nguyên). Việc ngắt rồi nối lại phòng TikTok cũng vậy. Vì thế hạn chế Tạm dừng giữa hiệp.
- **Không đổi được idol / gift của các vị trí khi PK đang chạy.**
- **Điểm trên bảng Rank không tự về 0.** Muốn làm lại từ đầu, xoá idol (nút ✕) rồi thêm lại, hoặc Import lại với điểm mong muốn.
- **Tắt server là mất hết dữ liệu** (idol, điểm, cấu hình PK). Trước khi tắt hãy vào **Import/Export → Export** và copy lại danh sách.
- Server **không có mật khẩu**. Chỉ dùng trong máy hoặc mạng nội bộ, đừng mở cổng ra internet.
- Không lấy được avatar tự động thì dán trực tiếp link ảnh vào ô avatar.

## 5. Gặp lỗi?

| Triệu chứng | Cách xử lý |
|---|---|
| `'pip' / 'python' is not recognized` | Chưa tick "Add to PATH" lúc cài Python. Cài lại Python và tick ô đó |
| Bấm Bắt đầu báo "Hãy kết nối và chờ 1 phòng TikTok Live..." | Chưa nối TikTok. Nhập username, bấm Kết nối, chờ `✔ Đã kết nối` |
| Báo "Hãy chọn idol..." hoặc "Hãy nhập gift_id kích hoạt..." cho vị trí N | Vị trí N chưa chọn idol hoặc chưa chọn gift kích hoạt |
| Báo "Không thể chọn cùng một idol..." / "Mỗi vị trí PK phải dùng một gift_id... khác nhau" | Hai vị trí đang trùng idol hoặc trùng gift. Chọn lại |
| Đã bắt đầu nhưng điểm không tăng | Người xem chưa gửi gift kích hoạt (xem danh sách "User đã được chọn vị trí"), hoặc vừa Tạm dừng rồi Bắt đầu lại nên phải gửi lại |
| Báo lỗi đỏ khi kết nối TikTok | Kiểm tra username đúng chưa và phòng có đang live không. Thử cập nhật: `pip install -U TikTokLive` |
| Quà muốn dùng không có trong danh sách | Danh sách có sẵn 643 quà, quà mới ra có thể chưa có |
| OBS không hiện gì | Mở thử link ngay trên trình duyệt. Nếu OBS ở máy khác, dùng IP của máy chạy server thay cho `localhost` |
| Lỗi cổng 8000 đang bị dùng | Đổi cổng: `set PORT=9000` rồi `python server.py` |

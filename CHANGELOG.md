# Changelog

Mọi thay đổi đáng kể của **Onmyoji Tool**. Bản mới nhất ở trên cùng.

---

## 3.1

### ⚠️ Bản này phải cài tay một lần

Từ 3.1 app đổi cách đóng gói, nên **nút Cập nhật trong bản 3.0 sẽ không đưa bạn
sang được 3.1**. Bản 3.0 vẫn chạy bình thường, chỉ là nó sẽ không báo có bản
mới nữa.

Cách chuyển:

1. Tải `OnmyojiTool-3.1.zip` ở phần Assets bên dưới release.
2. Giải nén ra, được thư mục `Onmyoji Tool`.
3. Chép `logs`, `cache`, `.env` (nếu có) từ chỗ cũ sang — không bắt buộc, chỉ
   để giữ lại nhật ký và cấu hình.
4. Chạy `Onmyoji Tool.exe` trong thư mục đó. Xoá bản 3.0 cũ đi.

Từ 3.1 trở đi nút Cập nhật hoạt động lại bình thường.

### Sửa lỗi không mở được sau khi cập nhật

Lỗi `Failed to load Python DLL ...\_MEIxxxxxx\python312.dll`.

Trước đây app gói kiểu **one-file**: mọi thứ nhét trong một exe, nên mỗi lần
chạy phải bung ~240 MB ra `%TEMP%` rồi mới nạp `python312.dll` từ đó. Bung
không xong — ổ đầy, `%TEMP%` nhiều rác, hoặc antivirus xoá file vừa ghi ra —
là app không mở được.

Giờ gói kiểu **one-dir**: các thư viện nằm sẵn trên đĩa cạnh exe, không bung gì
lúc chạy. Hết hẳn nhóm lỗi này, kèm theo:

- **Khởi động nhanh hơn nhiều** — không còn phải giải nén 240 MB mỗi lần mở.
- **Không đổ rác vào `%TEMP%`** nữa. Bản cũ mỗi lần bị tắt cứng lại bỏ lại
  240 MB; đo trên một máy thấy đọng **4.3 GB**.
- **Antivirus ít nghi hơn**, vì không còn cảnh ghi ra một DLL mới tinh rồi nạp
  nó ngay mỗi lần chạy.

Đổi lại: bản phát hành giờ là file `.zip` chứa cả thư mục, không phải một exe
rời.

Máy nào đang đọng rác `_MEI` cũ thì chạy `tools/fix_temp.bat` để dọn.

### Phụ bản ngự hồn

Tác vụ mới, chạy được cả hai vai:

- **Chủ phòng** — bấm Fight khi phòng sẵn sàng, rồi bấm qua màn kết thúc.
- **Thành viên** — không có nút Fight, chỉ bấm qua màn kết thúc.

Chọn vai **riêng cho từng cửa sổ**, không dùng chung.

Đặt số trận ở ô **Dừng sau** (mặc định 30), hoặc tick **Chạy vĩnh viễn** để
chạy đến khi bạn dừng.

Vài chỗ đáng nói:

- **Nút Fight nhận biết bằng màu, không phải hình.** Nút sáng và nút xám có
  cùng chữ, nên so khớp hình ảnh không phân biệt được (cả hai đều khớp 0.94).
  Đo độ bão hoà màu thì tách rất rõ: 149 khi sáng, 4.5 khi xám. Nhờ vậy bot
  không bấm Fight lúc đồng đội chưa vào lại phòng.
- **Mỗi màn kết thúc có điểm bấm riêng.** Màn Victory bấm vào góc phải dưới,
  vì giữa màn là cụm thức thần và hai avatar phần thưởng — bấm vào đó mở thứ
  khác chứ không thoát.
- **Đếm trận có chống dội.** Một trận hiện *hai* màn kết thúc, giữa chúng có
  một nhịp không khớp gì cả; nếu tính ngay thì màn thứ hai bị đếm thành trận
  mới. Log chạy thật từng cho ra 3 trận trong 44 giây.

### Thông tin liên hệ

Thêm khối **Liên hệ** ở cuối *Cài đặt chung* (F9), và ở cuối phần mô tả của mọi
release trên GitHub.

---

## 3.0

Trung tâm tác vụ mới, wiki nằm trong cùng cửa sổ, sửa lỗi tự dừng khi vẫn còn
vé.

Đây là bản **one-file** cuối cùng. Nút Cập nhật của nó không sang được 3.1 —
xem hướng dẫn cài tay ở trên.

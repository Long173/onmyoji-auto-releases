# Changelog

Mọi thay đổi đáng kể của **Onmyoji Tool**. Bản mới nhất ở trên cùng.

---

## 3.3

### Mỗi cửa sổ chạy một tác vụ, không còn chuỗi tác vụ

Trước đây mỗi cửa sổ giữ một **danh sách** tác vụ và tự chạy mục kế tiếp khi
xong mục trước. Đã bỏ hẳn, vì không ai xâu chuỗi tác vụ — người ta mở đúng phần
mình cần rồi chạy.

Cái chuỗi đó còn gây một lỗi khó chịu: bấm **Bắt đầu** ngay trên trang Ném đậu
lại khởi động Phá Kết Giới, còn trang Ném đậu thì hiện `Trong hàng chờ`.

Thay đổi bạn sẽ thấy:

- Trang chủ: cột **"Chuỗi tác vụ"** thành **"Tác vụ"**, mỗi cửa sổ một thẻ.
- Trên trang một tác vụ, nút **✕** (bỏ tác vụ) không còn — cửa sổ luôn có đúng
  một tác vụ, muốn đổi thì bấm **→ tên cửa sổ** ở trang tác vụ khác.
- **Bắt đầu tất cả** trên trang một tác vụ chỉ chạy cửa sổ đang đặt tác vụ đó,
  không kéo cửa sổ đang làm việc khác sang.
- Trạng thái `Trong hàng chờ` không còn tồn tại.

Cấu hình cũ **không mất**: thiết lập do bản trước ghi ra là một danh sách, và
app đọc mục đầu tiên còn tồn tại làm tác vụ của cửa sổ đó.

### Ném đậu: ngắm vào thức thần thay vì rải đều

Bot dựng một thư viện màu của các thức thần **thường** rồi ném vào những con nó
**không** nhận ra — vì con hiếm chỉ ghé một vòng rồi không quay lại, còn con
thường thì lặp lại, nên học con thường mới tổng quát hoá được.

Đo trên game thật: tỷ lệ hình bóng bị ném giảm từ **100%** (rải mù) xuống
**8.2%**, tức tập trung gấp 12 lần.

Nói thẳng phần chưa đạt: qua 30 vòng thu 411 mảnh, **chưa mảnh SSR/SP nào**, và
tổng mảnh mỗi vòng ngang với rải mù. Ngắm đã đúng nhưng chưa chứng minh được
việc ném trúng con hiếm cho ra mảnh của nó.

### Thư viện nhận dạng gọn lại

Thư viện ảnh 4.769 tấm (146 MB) được đóng thành một file chữ ký **1.5 MB**, nạp
trong 0.03 giây thay vì giải mã từng ảnh.

---

## 3.2

### Sửa lỗi Phá Kết Giới không chạy trên máy để display scaling khác 100%

Trên laptop để **125%**, Phá Kết Giới báo "tìm thấy quái" liên tục nhưng bấm
vào không mở được thẻ nào, rồi bấm loạn xạ vào chỗ trống.

Game không nhận biết DPI, nên ở 125% Windows chạy nó ở chế độ ảo hoá: game tin
rằng khung hình của nó là 898×507 và vẽ đúng ngần ấy, còn app — vốn nhận biết
DPI — hỏi Windows thì được trả lời 1122×633, vì đó là kích thước tính bằng
điểm ảnh thật trên màn hình. **Cả hai con số đều đúng. Trộn chúng vào nhau thì
không.**

Hậu quả đo được trên màn hình 125%:

- Ảnh chụp về là tấm 1122×633 với nội dung game nằm gọn ở **góc trên-trái
  898×507**, phần còn lại đen. Toàn bộ giao diện game nhỏ hơn ảnh mẫu 0.8 lần.
  `start.png` chỉ đạt **0.36** trong khi nút Attack đang hiện rõ trên màn hình.
- Tệ hơn: `section.png` đạt **0.91** khi khớp vào **vùng nền trống**. Bot bấm
  đúng chỗ trống đó, không thẻ quái nào mở ra, và vòng lặp đứng im.
- Click gửi đi bị Windows quy đổi lại theo DPI của **luồng gửi**. Cùng một toạ
  độ, gửi từ luồng nhận biết DPI thì *không có gì xảy ra*; gửi từ luồng không
  nhận biết thì vào trận.

Giờ mọi thao tác đo đạc, chụp hình và bấm đều chạy trong không gian toạ độ của
game. Cùng màn hình đó, sau khi sửa: `section.png` **0.991**, `start.png`
**0.986** — bằng đúng máy 100%. Đã chạy thử trọn vòng ở 125%: vào trận, đánh
xong, nhận thưởng, sang quái tiếp.

Giao diện của app vẫn nét, vì chỉ luồng nói chuyện với game mới đổi chế độ.

Kèm theo:

- **Resize theo client, không theo kích thước cửa sổ ngoài.** Trước đây app đặt
  kích thước ngoài cố định 1138×672 — con số chỉ đúng trên đúng một máy, nơi
  viền cửa sổ ăn 16×39. Giờ app đo viền của chính cửa sổ đó rồi cộng vào.
- **Không bấm vào chỗ trống nữa.** Nút tấn công vốn được bấm bất kể điểm khớp,
  vì ngay sau khi mở thẻ quái nó còn đang hiện ra. Giờ có sàn: dưới ngưỡng đó
  nghĩa là nút *không có trên màn hình*, app ghi log rõ lý do và bỏ lượt.
- **Log ghi thêm `dpi=` và `children=`** của cửa sổ game, để chẩn đoán từ xa.

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

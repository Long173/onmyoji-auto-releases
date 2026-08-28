# Changelog

Mọi thay đổi đáng kể của **Onmyoji Tool**. Bản mới nhất ở trên cùng.

---

## 3.11

### Phá Kết Giới

- Thua một trận thì tự bấm Refresh lấy bảng đối thủ mới. Trước đây tuỳ chọn này
  không bao giờ chạy: cờ hẹn bị xoá trước khi kịp tìm nút, mà bảng mất khoảng
  sáu giây mới quay lại. Nhận ra cả hai đường — bảng kết quả ngay sau trận, và
  dấu thua còn lại trên thẻ khi về danh sách (ảnh mẫu mới `lost.png`).
- Không còn kết giới nào đánh được thì tự đổi danh sách. Không phụ thuộc tuỳ
  chọn trên: một bảng có thẻ đã thua sẽ không bao giờ tự đổi, vì thua không tính
  là phá được kết giới.
- Bỏ tuỳ chọn "Vị trí target". Một cú bấm ở đó không xếp được thức thần nào, chỉ
  mở bảng chọn — một màn hình không ảnh mẫu nào nhận ra. Nó chạm tới 30 lần trên
  11.244 cú tấn công, và luôn sau khi đã bấm Bắt đầu.
- Bỏ nhánh bấm Refresh khi hết địch, cùng ảnh mẫu `rank.PNG`: game tự đổi bảng
  khi đánh hết chín, và ảnh mẫu đó cắt từ cửa sổ lớn hơn khoảng 20% nên chưa
  từng khớp.
- Nút Ready không còn bấm vào giữa dòng chữ. `click.png` là ảnh cắt một chữ cái,
  không phải cái nút.
- Vòng lặp có đường thoát khi gặp màn hình không nhận ra. Trước đây nó đứng im
  vô hạn — log có một vệt 12,5 phút không làm gì, chỉ dừng khi bấm tay.

### Phụ bản ngự hồn

- Bấm qua màn kết thúc ở góc phải dưới thay vì giữa màn hình, nơi game bày quà
  và xếp thức thần. Bấm vào đó mở phần thưởng thay vì đóng màn, và làm kẹt lượt
  chạy.
- Số trận không còn cộng dư một khi bật lại tác vụ lúc màn kết thúc của lượt
  trước còn hiện.

### Giao diện

- Nút Bắt đầu và Kết thúc gộp thành một ô, ở cả thẻ tác vụ lẫn bảng điều khiển.
  Một cửa sổ chỉ có thể đang chạy hoặc không, nên nút kia luôn bị vô hiệu.

### Công cụ

- `publish_release.py` cảnh báo khi CHANGELOG.md không có mục cho phiên bản đang
  phát hành.

---

## 3.6

### Thêm tác vụ Event

Tab mới: **Event**. Chọn một chỗ, bấm Bắt đầu, tool tự nhấn chỗ đó lặp lại cho
tới khi bạn dừng.

Không có nhận diện hình ảnh nào ở đây, và đó là chủ ý. Chữ trên nút bắt đầu mỗi
event một khác — event này ghi "Challenge", event khác ghi "Fight" — nên mẫu ảnh
cắt từ một event là mẫu ảnh hết hạn cùng event đó.

Cái không đổi là game luôn xếp nút "tiếp" vào **cùng một góc phải dưới**. Ghi lại
một lượt chạy thật cho thấy một toạ độ phục vụ được cả sáu cú nhấn của một lượt:

| màn hình | nút ở đó |
| --- | --- |
| màn event | Challenge / Fight / chữ khác |
| bày đội hình | Ready |
| xác nhận | trống Fight |
| đang đánh | không rơi vào nút nào, auto tự đánh |
| thắng + nhận thưởng | "Tap to continue" ×3 |

Đo trên game thật: **11 lượt trong 150 giây**, mỗi lượt khoảng 13 giây, chỉ bằng
một toạ độ. Mặc định 2 giây một nhấn cho ra 6,4 cú nhấn mỗi lượt — vừa đủ cho 6
cú cần thiết. Chọn 1 giây được nếu muốn nhanh hơn.

### Màn chọn toạ độ

Không nhập số. Bấm thẳng lên ảnh cửa sổ game, vì không ai biết nút mình cần nằm
ở "1030, 549" — người ta biết nó là *cái nút kia*.

Bấm một tấm ảnh thì chỉ chính xác bằng độ lớn của tấm ảnh, nên có ba thứ để chọn
được đúng từng điểm:

- **kính lúp phóng 9×** chỗ con trỏ đang chỉ, đậu ở góc xa con trỏ nhất nên không
  bao giờ che mất chỗ đang ngắm — bản đầu cho nó đi theo chuột và nó che đúng nút
  cần nhắm, vì nút đó nằm ở góc phải dưới;
- **mũi tên bàn phím** dịch từng điểm, giữ Shift dịch mười điểm;
- ảnh vẽ **1:1** khi màn hình đủ chỗ, nên phần lớn trường hợp không có phép co
  giãn nào nằm giữa con trỏ và điểm ảnh. Màn hình nhỏ thì ảnh co lại và chuột
  không trỏ tới được từng điểm — đó là lúc dùng mũi tên.

Dấu nhắm vẽ đen lồng trắng chứ không dùng màu vàng của app: đồ hoạ trong game
vốn vàng và nút bắt đầu là giấy màu kem, nên dấu vàng biến mất đúng chỗ cần thấy
nó — mà dấu không thấy được thì toạ độ không kiểm được.

### Cảnh báo chỗ nhấn có thể tốn ngọc

Hết vé, game mở bảng bán vé bằng ngọc. Chỗ nhấn mặc định nằm ngoài bảng đó nên
cú nhấn chỉ tắt bảng, nhưng chỗ nhấn đặt vào giữa màn hình thì có thể bấm nhầm
nút mua. Màn chọn toạ độ giờ báo đỏ khi điểm bạn chọn nằm trong vùng đó.

Đo trên một event, nên hiểu là "chỗ này chắc chắn nguy hiểm", không phải "chỉ chỗ
này mới nguy hiểm".

### Số đếm là số lần nhấn, không phải số trận

Tác vụ này không đọc màn hình nên không thể biết đã xong bao nhiêu trận. Thẻ cửa
sổ ghi "lần nhấn" đúng như vậy — một con số lệch dần khỏi thực tế còn tệ hơn
không có số nào.

### Toạ độ lưu dưới dạng chữ

PyQt không có kiểu lưu sẵn cho một cặp số, nên nó pickle cặp đó thành một khối
`@Variant(...)` trong registry. Khối đó đọc lại được, nhưng nó cất một pickle vào
chỗ mà người dùng đáng ra đọc thấy hai con số, và gắn giá trị đã lưu vào đúng
phiên bản PyQt đã ghi nó. Giờ lưu thành `1030,549`.

---

## 3.5

### Bản vá 3.4 không hoạt động — đây là bản thay

3.4 nói rằng khi bộ đếm đọc ra 0 thì bot sẽ thử đánh một trận để xác nhận. Phần
"thử đánh" chạy đúng, nhưng phần "xác nhận" thì không: bằng chứng "đã có trận"
được gắn vào một hàm **chưa từng chạy một lần nào** trên máy thật.

| trong log của một tài khoản thật | số lần |
| --- | --- |
| màn hình "đang trong trận" (chỗ gắn bằng chứng) | **0** |
| trận kết thúc | 281 |
| nhận thưởng | 451 |

Nên phép thử luôn kết luận hết vé — đúng thứ nó ra đời để tránh. Giờ bằng chứng
gắn vào **mọi** màn hình chứng minh đã có trận: kết thúc trận, nhận thưởng,
banner đang đánh, và cả thua trận (thua thì vé vẫn mất).

### Dùng chính lời game nói làm bằng chứng

Khi hết vé, game hiện chữ **"Not enough Realm Challenge Passes"**. Bot giờ đọc
câu đó — khớp 1.000 trên khung gốc so với 0.381 trên màn hình khác.

Đây là bằng chứng trực tiếp, khác hai cách cũ đều là suy đoán: đọc chữ số thì
đoán sai được (chữ `6` đạt 0.745 so với mẫu `0`, trên ngưỡng 0.72), còn "không
thấy trận nào" chỉ nói *có gì đó không diễn ra*, không nói *vì sao*. Có câu
thông báo thì bot biết ngay, không cần đọc số và không cần thử ba lần.

### Sửa lỗi vé không giảm dù bot chạy liên tục

Bấm Đánh xong bot trả về ngay, một giây sau đã bấm sang kết giới khác — lúc bàn
cờ đang biến mất, nên cú bấm rơi vào chỗ trống. Trong log thật, **một nửa** số
lần bấm thất bại như vậy:

```
14:43:50  Attack button score=0.943 — clicking
14:43:51  Enemy found (section) at (684, 377)
14:43:52  Attack button not on screen (score=0.370)
```

Vé đứng yên trong khi vòng lặp trông như đang làm việc. Giờ bot chờ bàn cờ rời
khỏi màn hình trước khi đi tiếp, tối đa 6 giây.

### Phép thử không còn rơi vào trạng thái chết

Trước đây phép thử thất bại một lần là bot ngừng hỏi lại mãi mãi — một lượt chạy
thật đã đứng ở `zero_reads=511` mà không đánh gì. Giờ nó thử tối đa 3 lần, và
nếu bạn tắt tự-dừng thì nó tự đặt lại để còn phát hiện được khi vé hồi.

---

## 3.4

### Sửa lỗi Phá Kết Giới báo "hết vé" khi vẫn còn vé

Bot dừng và báo hết vé trong khi tài khoản còn 6 vé.

Bộ đếm vé hiện dạng `6/30`. Bot đọc nó bằng cách cắt chữ số đầu tiên rồi so
với một ảnh mẫu chữ `0`. Đo trên chính màn hình đang lỗi:

| chữ số | điểm so với mẫu `0` |
| --- | --- |
| **`6`** của người dùng | **0.745** |
| `0` thật (trong `30`) | 0.926 |

Ngưỡng tin là **0.72**, nằm dưới cả hai — nên `6` bị đọc thành `0`. Ghi chú
trong mã còn khẳng định "các chữ khác đều dưới 0.5", nhưng con số đó chỉ đo
trên `/`, `3`, `0` của chuỗi `0/30`, chưa từng thử với `6`.

**Cách sửa không phải là nâng ngưỡng.** Nâng lên 0.85 tách được 0.745 khỏi
0.926, nhưng biên chỉ còn 0.08 và chữ `8` cũng tròn — sẽ vấp lại.

Giờ bộ đếm không còn tự mình kết thúc một lượt chạy. Đọc ra 0 ba lần liên tiếp
thì bot **bấm đánh một kết giới** và xem kết quả:

- **trận bắt đầu** → còn vé, kết quả đọc sai, bỏ qua và chạy tiếp
- **không có trận nào** → hết vé thật, kết thúc

Một trận diễn ra là bằng chứng đã tiêu được vé — thứ mà bộ đếm chỉ đoán.

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

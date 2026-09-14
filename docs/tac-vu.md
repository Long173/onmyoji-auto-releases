# Các tác vụ auto

Từng vòng lặp hoạt động ra sao, và những chỗ đã trả giá để tìm ra cách nhận
biết đúng màn hình.

---

## Vòng lặp Phá Kết Giới

Mỗi vòng chụp **một** khung hình rồi đi qua chuỗi handler theo thứ tự ưu tiên;
handler nào khớp template trước thì xử lý và kết thúc vòng đó.

```
chụp khung hình (PrintWindow)
        │
        ├─ hết vé?            -> dừng, báo hoàn thành
        ├─ có lời mời truy?   -> bấm Từ chối (hoặc Chấp nhận)
        ├─ popup cooldown?    -> đóng popup, tìm mục tiêu khác
        ├─ nhận thưởng?       -> click 2 lần, +1 trận
        ├─ sẵn sàng?          -> xác nhận, rồi click slot đã chọn
        ├─ đang đánh?         -> chờ 5s
        ├─ nút START?         -> click
        ├─ chưa vào PKG?      -> mở màn hình PKG
        ├─ thấy địch?         -> click địch, rồi click Tấn công
        ├─ ếch?               -> click, rồi click Tấn công
        ├─ kết thúc trận?     -> click
        ├─ thua?              -> click, đánh dấu cần refresh
        ├─ màn xếp hạng?      -> refresh danh sách
        └─ hộp thoại OK?      -> đóng
```

Nếu cùng một màn hình (START hoặc danh sách địch) khớp liên tiếp
`STUCK_LIMIT = 10` khung hình, bot coi như có modal vô hình đang nuốt click và
bấm vào góc trái-trên để đóng nó.

## Phụ bản ngự hồn: nhận biết nút bằng **màu**, không phải hình

Nút "Fight" trong phòng co-op có hai trạng thái: **vàng** khi bấm được, **xám**
khi chưa đủ người. Cả hai cùng một chữ, cùng một khung.

So khớp ảnh **không tách được**, và đây là số đo chứ không phải phỏng đoán:

| Cách | Cách biệt giữa vàng và xám |
| --- | --- |
| Ảnh xám (mặc định của app) | 0.00 — khớp **cả hai** ở 0.94 |
| Ảnh màu | 0.04 — vẫn không dùng được |
| **Bão hoà màu (HSV)** | **144.5** — vàng 149, xám 4.5 |

Lý do so khớp thất bại: `TM_CCOEFF_NORMED` trừ giá trị trung bình trước khi so,
nên một khối màu lệch đều nhau gần như bị triệt tiêu.

Nên có hai tầng, mỗi tầng dùng đúng công cụ:

1. `fight.png` so ảnh xám → **"đang ở trong phòng"** (cố ý khớp cả hai trạng
   thái; cách biệt 0.684 so với các màn khác)
2. Bão hoà vùng nút ≥ 80 → **"nút bấm được"**

Tầng 2 quan trọng hơn vẻ ngoài: **3 giây sau mỗi trận**, phòng đã hiện lại
nhưng đồng đội chưa quay về, nút còn xám. Bot chỉ so hình dạng sẽ bấm ngay lúc
đó, mỗi vòng.

## Mỗi màn kết thúc có điểm bấm riêng

Một trận có **hai** màn kết thúc, và chúng không giống nhau:

| Màn | Bấm ở | Vì sao |
| --- | --- | --- |
| Victory | **(1055, 445)** | Giữa màn là cụm thức thần, hai avatar phần thưởng ở ~(680,320) và ~(790,320). Bấm vào đó **mở thứ khác** chứ không thoát — đây là lỗi làm run thật đứng lại. Góc phải dưới là nền đất trống trên mọi khung đã ghi |
| Tap to continue | (561, 316) | Bấm đâu cũng được, giữa màn là đủ |

## Đếm trận: theo **cạnh lên**, có chống dội

Màn kết thúc đứng vài giây, bot quét mỗi giây — đếm theo vòng quét sẽ ra 4–5
trận cho một trận thật. Bot nhớ trạng thái vòng trước, chỉ +1 khi màn hình
*chuyển vào* trạng thái kết thúc.

Chỉ vậy vẫn chưa đủ: giữa màn Victory và màn daruma có **một nhịp không khớp
template nào**, và xoá cờ ngay nhịp đó khiến màn thứ hai bị tính thành trận
mới. Log chạy thật cho thấy 3 trận trong 44 giây, hai trận cách nhau 6 và 16
giây. Giờ phải **4 vòng liên tiếp** vắng mặt mới xoá cờ.

Cả hai lỗi trên chỉ lộ khi chạy thật — bản ghi màn hình không cho thấy được.

Đếm ở đây **đáng tin**, khác cái đã bỏ ở Phá Kết Giới: raid phải suy ra số trận
từ việc bắt gặp bảng thưởng (bỏ sót là lệch dần), còn ở đây bot đếm chính hành
động nó vừa làm.

Ô "Dừng sau" là `QSpinBox` với `specialValueText` — đặt về 0 thì hiện chữ
**"Không giới hạn"** thay vì số 0, nên không có giá trị ma nào phải giải thích.

## Khi nào mới được đọc số vé

Vùng đếm vé là **một hình chữ nhật toạ độ cố định** ở góc trên phải của bảng kết
giới. Trước đây vòng lặp đọc nó ở **đầu mỗi vòng, vô điều kiện** — kể cả lúc
đang trong trận, khi ô đó đang là hiệu ứng/nền trời. Bộ tách chữ số tìm ra một
số "0" đủ giống trong đó, và run bị dừng giữa trận dù còn vé.

Giờ có hai lớp chặn:

1. **Chỉ đọc khi đã xác nhận đang ở bảng.** Ảnh mẫu danh sách địch (`section`)
   là dấu hiệu dương duy nhất cho biết bảng đang hiện và không có gì che. Mọi
   handler trạng thái khác (đang trong trận, popup hồi chiêu, bảng nhận thưởng,
   nhắc sẵn sàng, nút START, cửa vào kết giới) chạy **trước** và cắt vòng lặp —
   nên kể cả `section` khớp nhầm với ảnh trong trận thì "đang trong trận" vẫn
   thắng.
2. **Một lần đọc không đủ.** Phải đọc ra 0 **3 lần liên tiếp**, cách nhau 1
   giây, mới kết luận hết vé. Màn hình đang trượt vào có thể che ô đếm đúng một
   khung hình.

Trong lúc chờ xác nhận, bot **đứng im chứ không bấm đánh** — bấm là vào trận, và
lần đọc kế tiếp lại rơi vào màn hình sai. Đọc ra khác 0 là đếm lại từ đầu.

Tắt "Tự dừng khi hết vé" thì hết vé bot cũng không bấm nữa, chỉ nằm chờ.

## Đọc số vé

Bộ đếm góc phải trên hiện `0/30`. Bot **không** so khớp cả chuỗi đó, vì hai lý
do khiến cách ấy không bao giờ đúng:

- `0/30` là chuỗi con của `10/30` — template trượt sẽ khớp cả hai, tức là báo
  hết vé ngay cả khi còn 10 vé.
- Chữ căn giữa trong khung, nên mọi ký tự dịch ngang khi tử số thêm chữ số;
  toạ độ cố định cũng không tin được.

Cách làm: cắt dải chữ, tách thành từng ký tự bằng ngưỡng sáng, rồi **chỉ so ký
tự trái nhất** — chữ số đầu của tử số — với mẫu `0` (`ticketZero.png`, cắt từ
màn hình thật). Đúng với mọi mẫu số, `/30` hay `/50`.

Đo trên khung hình thật: `0` = **1.000**, `3` = 0.357, `/` = −0.363, và mô
phỏng tử số hai chữ số = −0.380. Ngưỡng đặt 0.72.

## Lời mời truy (co-op Wanted Quest)

Người chơi khác mời truy thì hộp thoại đè lên bàn cờ và nuốt mọi click bên
dưới — đây là lý do auto đứng im. Bot nhận diện hộp thoại rồi bấm nút bạn chọn.

Chỉ có hai lựa chọn, **Từ chối** hoặc **Chấp nhận**; hộp thoại luôn được trả
lời. Không có lựa chọn "để nguyên" vì để nguyên chính là trạng thái làm auto
đứng.

Điểm cần lưu ý: bot **bắt buộc thấy cả hai nút** Accept và Refuse, đúng thẳng
hàng và cách nhau `WANTED_BUTTON_GAP = 90px`, mới bấm. Chỉ khớp một dấu ✓ xanh
là chưa đủ — game còn nhiều hộp thoại xác nhận khác cũng có dấu ✓, và bấm nhầm
vào đó sẽ gây hậu quả khó lường. Hai nút xếp chồng như vậy chỉ có ở hộp thoại
này.

Hai template (`wantedAccept.png`, `wantedRefuse.png`) cắt sát vào đĩa nút, so
khớp theo **màu** vì chuyển sang ảnh xám thì ✓ xanh và ✗ đỏ gần như giống hệt.
Đo trên khung hình thật: 1.00 khi có hộp thoại, cao nhất 0.58 ở màn hình khác —
ngưỡng đặt 0.75.

## Đọc bảng kết quả Ném đậu: tên và số mảnh

Ba bài toán nhận dạng trên cùng một bảng, và **cả ba đều từng hỏng theo cùng
một kiểu**: so ảnh trong đó phần lớn pixel là thứ *giống hệt nhau ở mọi thẻ*,
nên hai ảnh đã "đồng ý" với nhau trước khi so đến chỗ thật sự khác.

| chỗ | phần nền chung | hậu quả khi để nguyên |
|---|---|---|
| Số mảnh `x4` | dấu `×` | chữ vàng đọc 3 thành 6; xám hoá còn 0.921 vs 0.918 |
| Tên thức thần | dải ruy băng | Kanko ↔ Kappa 0.938, ngưỡng 0.95 |
| — | — | và hai ảnh **cùng tên** chỉ khớp nhau 0.65–0.74 |

Cách sửa giống nhau: **cắt bỏ phần chung, chỉ so phần riêng.**

- **Số**: cắt riêng chữ số khỏi dấu `×`, nhị phân hoá, so hình dạng. Đúng
  0.51–1.00, sai không quá 0.30.
- **Tên**: cắt sát vùng chữ, và **loại trước theo bề rộng** (lệch quá 1px thì
  không cần so pixel). Nhầm cao nhất tụt 0.938 → **0.787**, biên nới từ 0.012
  lên **0.072**.

Cắt sát còn được một thứ quan trọng hơn con số: nó **khái quát hoá**. Hai ảnh
cùng tên trên ruy băng khác sắc giờ khớp nhau 0.86–0.96, nên một ảnh phủ được
nhiều biến thể. Trước đó thư viện chỉ *thuộc lòng* — mỗi ảnh nhận ra đúng bản
sao của chính nó, nên phải nhét đủ 128 ảnh cho 82 tên.

Ruy băng đổi sắc theo **độ hiếm** thức thần, nên `Koi.png`, `Koi (2).png`,
`Koi (3).png` là ba ảnh của cùng một tên — hậu tố `(n)` bị bỏ khi đọc nhãn. Đo
thật: bỏ hết biến thể chỉ giữ một ảnh mỗi tên thì **7 biến thể mất nhận dạng**,
nên chúng có chỗ đứng.

**Đã thử OCR tự dựng theo từng chữ cái và bỏ.** Ghi lại để đừng ai thử lại mù
quáng: cắt chữ đạt **16/16 tên**, nhưng nhận dạng chỉ **3/16** dù đã thử so
nhị phân co cùng cỡ, so nhị phân giữ cỡ, so ảnh xám, và chuẩn hoá cực ruy băng.
Chữ cái chỉ **7–10 pixel** — sai lệch khử răng cưa theo màu nền lớn ngang khác
biệt giữa hai chữ cái khác nhau. Muốn làm thật cần OCR có mô hình, mà cái rẻ
nhất cũng thêm vài chục MB vào bản build vốn đã bị antivirus soi.

Cách đang dùng: bot **tự lưu ảnh dải tên chưa đọc được** vào
`cache/parade-unknown/`. Xem ảnh, đặt tên file, bỏ vào `screenshots/DemonParade
/names`. Một đợt 259 ảnh cho ra 125 tên khác nhau.

`test_no_two_different_names_look_alike_enough_to_be_confused` chạy đúng đường
so khớp thật và đỏ ngay khi một tên mới bóp biên về không — hỏng lộ ở test, chứ
không phải ở bảng thống kê âm thầm cộng mảnh vào nhầm thức thần.

## Ném vào con hiếm: nhận dạng bằng màu

Ném trúng ai mới đáng, nên vòng lặp phải phân biệt được thức thần. Nhận bằng
**màu, không phải bằng hình** — đo chứ không đoán:

| cách so | số cụm từ 220 sprite | cụm chỉ 1 ảnh |
|---|---|---|
| so pixel ảnh cắt | 174 | 150 |
| **biểu đồ hue + saturation** | **62** | 18 |

Thức thần vừa đi vừa xoay, nên dáng đổi nhiều hơn danh tính. Bảng màu thì
không — và mỗi con ở đây được vẽ theo một bảng màu riêng.

Không cần biết tên, chỉ cần bậc hiếm. Thư viện là một thư mục mỗi bậc trong
`screenshots/DemonParade/rarity/`.

**Đậu mới là thứ hết trước, không phải thời gian.** 250 hạt, mỗi phát 10 hạt là
**25 phát**, tiêu sạch trong khoảng 15 giây của vòng 60 giây. Nên vòng lặp
không thể thấy gì ném nấy rồi mong con hiếm nằm trong đó — nó **giữ đậu cho
SP/SSR**, và chỉ trong `DUMP_LAST_SECONDS` cuối mới rải nốt phần thừa vào ai có
mặt, vì đậu không dồn sang vòng sau.

Đây là đảo ngược có chủ đích so với bản trước, vốn xếp hạng mọi con rồi luôn
ném vào con tốt nhất đang có. Xếp hạng thì tiêu ví vào bất kỳ ai đi qua trước.

Vì thế con không có trong thư viện (`None`) **không được ném**, ngược với trực
giác. Giá của hai loại sai không bằng nhau: bỏ sót một SP mất một phát, còn coi
mọi con chưa gán nhãn là đáng ném thì tiêu sạch ví vào con thường và **vẫn** mất
con SP đó.

Chỉ cần gán nhãn **SP/SSR** là bot chạy đúng. Nhưng vẫn giữ ba thư mục N, R, SR
dù không có gì đọc tới chúng: đó là **tập đối chứng âm**. Không có chúng thì
không đo được tần suất một con thường bị đọc nhầm thành SSR, mà mỗi lần nhầm là
phí đúng số đậu cả thiết kế này sinh ra để giữ.

**Trần kích thước là chỗ dễ hỏng nhất.** Đợt gán nhãn đầu đặt trần 250×220 và
cho ra 106 nhóm **không có lấy một SSR hay SP nào**. Thu lại ở 520×420 thì con
SSR đầu tiên hiện ra ngay: **118 rộng × 264 cao**. Trần cũ giết nó bằng **chiều
cao**, không phải chiều rộng — con này cao và hẹp, không hề to bè.

Chi tiết đó đáng nhớ, vì suýt nữa đã sửa nhầm nửa còn lại. Đúng là 34% sprite
thu lại rộng hơn 250 thật, nhưng chúng là **hai con đi sát nhau dính thành một
khối** (xem `MAX_ASPECT`), không phải artwork lớn. Chiều rộng là dấu vết đánh
lạc hướng; chiều cao mới là chỗ mất dữ liệu.

Nếu một bậc hiếm không bao giờ xuất hiện, nới trần trong
`tools/collect_figures.py` trước khi nghi bất cứ thứ gì khác.

Biên hiện tại, đo trên toàn bộ 18.939 cặp khác bậc của 221 ảnh: cặp giống nhau
nhất đạt **0.828** so với ngưỡng **0.85** — chưa con nào bị đọc nhầm bậc, nhưng
biên chỉ **0.022**. `test_no_two_ranks_come_close_to_being_confused` giữ chỗ đó.

Hai phép đo trên dữ liệu thật, sau khi gán nhãn 13 nhóm SP/SSR từ 10 vòng:

- **0/179 báo nhầm.** 179 nhóm người dùng đã xem và loại — tập đối chứng âm
  thật sự — không nhóm nào bị đọc thành SP/SSR. Đây là hướng sai đắt nhất: mỗi
  lần nhầm là phí đúng số đậu cả thiết kế sinh ra để giữ.
- **114/114 dáng nhận ra được** khi bỏ chính nó khỏi thư viện, và không dáng
  nào bị con thường vượt mặt. Có phần vòng quanh, vì các dáng này do chính bước
  gom nhóm ở ngưỡng 0.85 chọn ra; kiểm chứng thật là vòng chạy tới.

Lưu ý một phép đo **sai đề** để đừng ai lặp lại: thử "bỏ-một-ra" cho ra 0%
nhận dạng đúng. Không phải bộ nhận dạng hỏng — thư viện giữ **một ảnh mỗi thức
thần**, nên bỏ ảnh đó ra là không còn gì để khớp. Câu hỏi thật (một *dáng mới*
của con đã biết có đọc đúng không) do bước gom nhóm trả lời: một dáng chỉ vào
được nhóm khi vượt đúng ngưỡng 0.85 đó.

**Đã thử lấy độ hiếm từ dữ liệu wiki và bỏ.** `cache/wiki/shikigami.json` có sẵn
287 thức thần kèm `rarity` và ảnh chính thức — nhìn thì như một đường tắt thay
hẳn việc gán tay. Đo trên Asura (SSR, con đầu tiên xác định được):

| so ảnh chính thức với | điểm |
|---|---|
| sprite Asura trong game | **0.348** |
| một con **R** không liên quan | **0.727** |

Ảnh wiki là chân dung 120×120, sprite là toàn thân nhìn từ xa trên cầu — bảng
màu không cùng một thứ. Dùng nó sẽ xếp Asura vào R. Vẫn phải gán tay.

Dữ liệu wiki vẫn có ích một việc: **đối chiếu nhãn**. Ruy băng trên đầu con
Asura đọc được chữ "As", tra wiki ra đúng một kết quả `Asura → SSR`, xác nhận
nhãn người gán mà không cần tin vào mắt.

## Máy tự gán nhãn con thường

Không cần người nhìn nữa. Luật rút ra từ chính dữ liệu: **nhóm nào xuất hiện ở
≥2 vòng thì là con thường.** Con hiếm ghé đúng một vòng rồi không quay lại, con
thường thì có.

Kiểm trên 192 nhóm người dùng đã gán tay:

| | |
|---|---|
| tự gán đúng con thường | **132 / 179** |
| **con hiếm bị gán nhầm** | **0 / 13** |
| con thường bỏ sót | 47 |

Sai sót chỉ đi theo hướng vô hại: con thường bỏ sót vẫn nằm ở diện "chưa biết"
nên vẫn bị ném — mất chút chọn lọc, không bao giờ mất con hiếm.

```
python tools/grow_library.py --cycles 5 --rounds 10 --hwnd 0x60586
```

Đo thật qua 50 vòng: thư viện con thường 3.204 → 4.446 mẫu, và số nhóm cần mắt
người mỗi 10 vòng tụt từ **192 xuống 33**. Số nhóm tự xếp được mỗi chu kỳ giảm
dần (41 → 60 → 30 → 19 → 26), tức đã gần bão hoà.

Thước đo tiến bộ **không phải** số nhãn, mà là **tỷ lệ hình bóng bị ném** trên
màn: nó bắt đầu ở 100% (quét mù), xuống 33.6% sau đợt gán tay đầu, và mỗi con
thường học thêm lại đẩy nó gần hơn về tỷ lệ hiếm thật.

Quy trình làm giàu dữ liệu:

```
python tools/collect_figures.py 10 --hwnd 0x60586   # mỗi vòng tốn 1 vé
python tools/cluster_figures.py cache/figures --min-sightings 5
# xem cache/label-rarity/_all.png, ghi lại số của những nhóm là SSR/SP
python tools/promote_group.py SSR 003 007
```

`--hwnd` cần khi máy đang mở nhiều client: `find_game_window` trả về cửa sổ đầu
tiên hệ điều hành liệt kê, và trên máy ba cửa sổ nó từng trả về một trận đánh
boss thay vì đám rước.

`promote_group.py` chép **mọi dáng** trong nhóm, không chỉ ảnh trên bảng — với
bậc mà vòng lặp phải hành động theo, một dáng không nhận ra là một lần ném bị
bỏ lỡ.

---

[← Về trang chính](../README.md)

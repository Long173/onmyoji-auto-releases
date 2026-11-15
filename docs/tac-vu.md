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
        ├─ hết vé?            -> bật "hết vé thì đánh hội": sang tab Guild
        │                        còn lại (hoặc hết cả lượt hội): dừng, báo xong
        ├─ có lời mời truy?   -> bấm Từ chối (hoặc Chấp nhận)
        ├─ popup cooldown?    -> đóng popup, tìm mục tiêu khác
        ├─ nhận thưởng?       -> click 2 lần, +1 trận
        ├─ sẵn sàng?          -> xác nhận, rồi click slot đã chọn
        ├─ đang đánh?         -> chờ 5s
        ├─ nút START xám?     -> không bấm: đóng thẻ, chờ cooldown
        ├─ nút START sáng?    -> click, chờ trận vào
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

Trên bảng Guild, nút Tấn công **xám** nghĩa là cooldown chưa hết; bấm vào chỉ
ra popup "Cooldown time is not yet up!". Bot đo độ bão hoà màu của nút (xám ~25,
sáng ~150, ngưỡng `ATTACK_GREY_SATURATION = 80`) và không bấm nút xám mà đóng
thẻ, chờ 5s rồi xem lại. Xám liền hơn 10 phút thì bấm thử một lần cho game tự
trả lời, phòng khi đọc nhầm màu.

"Hết vé thì đánh kết giới hội": khi bảng cá nhân được xác nhận hết vé (game báo
không đủ vé, hoặc 3 lần bấm thử không vào trận) bot bấm tab Guild
(`geometry.GUILD_TAB_POINT`) thay vì dừng. Danh sách thẻ đã gạch và lệnh refresh
đang chờ đều bỏ, vì chúng thuộc bảng cũ. Bấm `GUILD_SWITCH_ATTEMPTS = 3` lần mà
bảng vẫn là bảng cá nhân (chưa vào hội) thì dừng như thường. Hết lượt hội thì
dừng theo "Tự dừng khi hết vé".

Nút **sáng** bấm mà không vào trận nghĩa là kết giới đã bị người khác phá: sau
`START_REFUSAL_LIMIT = 2` lần bấm (mỗi lần chờ tới 6s cho trận vào) bot gạch thẻ
đó khỏi danh sách và chuyển mục tiêu khác. Trước khi gạch, bot nhìn lại một lần:
nút đã biến mất thì là trận chỉ tải chậm, không gạch.

## Đấu PvP: chỉ bấm công tắc đang **tắt**

Dựng từ bản quay 18 trận xếp hạng (`recordings/pvp`, Tier 1 → Tier 5). Một trận
khoảng một phút, luôn đi qua cùng các màn:

```
sảnh ── Battle ──> ghép trận (~15s) ──> chọn thức thần ──> trận ──> kết quả ──> sảnh
                                                                  │
                                       lên bậc / thành tựu  <─────┘ (thỉnh thoảng)
```

Có hai kiểu màn chọn thức thần, và ở Tier 5 cả hai xen kẽ nhau:

- **Chọn cùng lúc** (chữ "Fight", đếm 30 giây): game tự đặt đội đã lưu, chỉ cần
  bấm **Ready**.
- **Chọn theo lượt** (trống "Round 1…4"): mới vào thì auto pick luôn **tắt**, nút
  ghi "Auto Deploy". Bấm một lần thì nó thành "Cancel Auto" và game tự chọn hết.

Mỗi nút tác vụ bấm đều là một **công tắc mà chữ trên nó cho biết trạng thái**, và
tác vụ chỉ bấm khi nó đang tắt — bấm nhầm lúc đang bật là tắt mất cái vừa bật:

| Nút | Đang tắt | Đang bật | Tách được bao xa (ảnh xám) |
|---|---|---|---|
| Ready | chữ đỏ | chữ xám, có dùi trống | 0,95 / tối đa 0,84 — ngưỡng 0,9 |
| Auto Deploy | "Auto Deploy" | "Cancel Auto" | 0,99 / 0,57 |
| Auto trong trận | "Manual" | "Auto" | 0,85 / 0,59 |

Chữ đổi chậm hơn cú bấm một chút (Ready mờ dần từ đỏ sang xám hơn một giây), nên
mỗi nút bị chặn bấm lại trong 3 giây — Ready là 5 giây. Trận nào cũng bắt đầu ở
Manual; trong bản quay người chơi bấm sang Auto bằng tay gần như mọi trận.

Kết quả, lên bậc và bảng **"Achievement Complete"** được chạm qua ở cùng một chỗ
(giữa đáy màn hình). Phần thưởng 1/3/5 trận thắng đầu tuần đến qua chính bảng
thành tựu đó (ở trận thắng thứ 1, 3, 5 trong bản quay); "Wins This" thì tự cộng,
không cần bấm. Thắng hay thua đều ra cùng chữ "Tap to continue", nên tác vụ
không cần biết.

Bảng thành tựu và màn lên bậc vẽ **đè lên sảnh**, và trống Battle vẫn khớp xuyên
qua chúng — nên chúng phải được xét trước Battle.

### Dừng: mục tiêu điểm, hoặc hết giờ

Trước mỗi lần bấm Battle, tác vụ đọc điểm dưới bậc ở sảnh (`1958/2000`) và dừng
khi đủ mục tiêu: 2400, 2700, hoặc Danh sĩ = 3000. Hết giờ mở PvP thì trống
Battle thành **"Prac."** (luyện tập); tác vụ không bấm nó mà dừng luôn.

**Đọc điểm** dùng cách tách chữ của ô vé (`raid_tickets.py`): cột sáng trong một
dải cố định tách thành từng chữ. Ngưỡng sáng từ 100 tới 150 đều tách đúng cả 20
sảnh trong bản quay; chọn 135. Nhưng **so chữ** thì không mượn được: trượt mẫu
trên chữ đã đệm viền không phân biệt được 5, 6 và 8 — một chữ "6" của 1760 được
0,90 là 5, 0,88 là 8 và chỉ 0,84 là chính nó. Chữ ở đây rộng 7 px, khác nhau một
hai điểm ảnh ở một góc, mà trượt vài pixel là xoá mất. Nên không trượt nữa: cắt
chữ sát mực, kéo về một cỡ cố định, so từng điểm với **nhiều** mẫu mỗi chữ (một
mẫu "6" duy nhất vẫn thua "5", vì cùng một chữ rơi lên lưới điểm ảnh khác nhau
mỗi khung). Bỏ từng chữ ra khỏi tập mẫu rồi đọc lại nó: 171/171 chữ đúng, hơn
chữ kế tiếp ít nhất 0,14.

**Danh sĩ không có điểm.** Từ Danh sĩ trở lên sảnh đếm sao, "5/30" cạnh một ngôi
sao, thấp hơn dòng điểm khoảng 10 px. Quy tắc (do người chơi đưa ra): thấy số
không đủ 4 chữ số là đã lên Danh sĩ — mục tiêu cao nhất — nên tác vụ dừng. Tác vụ
đọc cả hai dòng; trên 21 sảnh thường dòng sao chưa lần nào ra một "N/M" ngắn, còn
trên sảnh Grand Celebrity (ảnh người chơi gửi) nó đọc đúng "5/30".

**Bản chụp thật khác bản quay.** Lần chạy thật đầu tiên dừng ngay ở sảnh đầu: dấu
"/" ở đó rộng 4 px, còn mọi dấu "/" trong bản quay (1136x640 thu về 1122x633) chỉ
3 px, và chỉ được 0,66. Chữ vẽ đúng ở cỡ chuẩn rộng hơn chữ bị thu nhỏ một điểm
ảnh, chữ hẹp chịu ảnh hưởng nhiều nhất. Các mẫu `*_live*` trong
`screenshots/Duel/digits` cắt từ chính lần chụp đó.

Đọc không ra thì trả về *không đọc được*, không bao giờ là một con số đoán. Có
mục tiêu mà sảnh không đọc được 6 lần liền thì tác vụ **dừng** — một bảng mờ dần
qua sảnh chỉ tốn một hai lần. Thà dừng ở đó còn hơn đánh tiếp qua mục tiêu mà
không thấy nó. Từ Danh sĩ trở lên có cấm thức thần, tác vụ không làm thay được.

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

**Không có vai chủ phòng / thành viên.** Trước đây mỗi cửa sổ phải chọn vai, và
chọn sai là cách duy nhất làm hỏng một phòng: chủ phòng bị đặt nhầm thành
"thành viên" thì ngồi mãi trong phòng đủ người. Giờ mọi cửa sổ chạy cùng một
vòng lặp — chỉ chủ phòng mới có nút Fight, nên cửa sổ thành viên không bao giờ
tìm thấy nó và chỉ bấm qua màn kết thúc.

**Tuỳ chọn "Đi 3 người".** Chỉ cần một đồng đội là nút Fight đã sáng, nên màu
nút không cho biết phòng đã đủ 3 người hay chưa. Ô khách còn trống thì có vòng
dấu "+" (`emptySlot.png`), và bật tuỳ chọn này thì chủ phòng chỉ bấm khi không
còn ô nào có dấu đó.

| Ô khách | Điểm `emptySlot.png` |
| --- | --- |
| Trống | 0.985 – 1.000 |
| Có người | ≤ 0.51 |
| Trống nhưng bị dòng "Invitation sent." che | ~0.55 |

Dòng cuối là lý do phải **chờ 3 giây**: thông báo mời đè lên vòng "+", nhìn
một lần thì giống ô đã có người. Nó tắt trong chưa tới một giây trên mọi bản
ghi, nên phòng phải không có dấu "+" liên tục 3 giây mới bấm, và hễ thấy lại
dấu "+" là đếm lại từ đầu. Bảng mời bạn bè cũng che ô, nhưng nó làm tối cả
màn, nên nút Fight không còn sáng và tầng 2 ở trên đã chặn sẵn.

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

## Đếm SSR/SP trên bảng kết quả: đọc màu chữ độ hiếm

Mục tiêu của ném đậu là mảnh SSR/SP, mà ô SSR lại là ô bộ đọc kém nhất: số
`x1` quá mảnh để tách nét, tên thì thường chưa có trong thư viện. Trước đây cả
1.227 trận trong log của một user không ghi nhận được mảnh SSR nào, trong khi
cache vẫn lưu ảnh ô Kuzunoha và Higanbana (SSR) mà tool không đọc ra.

Mỗi ô có một chữ cái màu ngay bên trái tên (N, R, SR, SSR), và mép phải của
nó nằm sẵn trong `NAME_BOX`. Đo trên 64 dải tên thật và ảnh mẫu 7 ô (hue
OpenCV 0–179):

| độ hiếm | màu mép chữ | số ảnh |
|---|---|---|
| N | không có điểm ảnh màu (chữ xám) | 17 |
| R | hue 102–103 | 25 |
| SR | hue 141–142 | 20 |
| SSR | hue 17, cam sang vàng | 2 |

Các nhóm cách nhau xa nên dải hue để rộng. **SP chưa từng chụp được**: màu chữ
SP mà không rơi vào dải nào thì đọc là "không rõ" và ô đó được lưu vào
`cache/parade-unknown/` với nhãn `rarity-N`, thay vì đoán sang độ hiếm gần nhất.

Đếm SSR/SP chỉ dựa vào màu chữ, không cần tên hay số, nên ô SSR không đọc được
tên vẫn được tính. Log mỗi vòng ghi `[SSR] ? x? … — SSR/SP: 1`, và thông báo
cuối có `SSR/SP: n`.

## Quỷ vương: chọn con to nhất, rồi dồn đậu vào nó

Ném trúng quỷ vương đã chọn được gấp ba mảnh, nên mảnh SSR/SP gần như chỉ có
đường này: chọn đúng con SSR/SP làm quỷ vương, rồi ném trúng nó.

**Chọn** (`parade_pick.py`). Màn chọn chỉ có ba bóng đen, không tên, không độ
hiếm. Nhưng bóng SSR/SP thường to hơn: trên 205 màn chọn có người gán nhãn, chọn
bóng to nhất (so với cỡ thường gặp ở đúng cột đó, vì ba cột đứng ở độ sâu khác
nhau) chọn trúng SSR/SP 9 trên 13 lần có SSR/SP. Bấm cố định một chỗ như trước
chỉ trúng khoảng một phần ba. SSR/SP chỉ xuất hiện trong khoảng 6% số màn chọn.

**Ném dàn đều.** 250 đậu, 10 đậu một lần là 25 lần ném, và hết đậu là vòng kết
thúc ngay. Ném theo tốc độ của game thì khoảng 45 giây đã hết, còn cả chục con
chưa ra, mà quỷ vương ra lúc nào là ngẫu nhiên. Nên trước khi bộ đếm trên cùng về
0 (con thứ 36 đã vào sân), cứ 2 giây mới ném một lần; về 0 rồi thì xả hết trong 8
giây.

**Bám quỷ vương** (`parade_boss.py`). Game tự đánh dấu quỷ vương: chữ "Picked"
xoay vòng quanh nó. Tìm chữ này trên ảnh xám: qua 3.402 khung video, nó bắt
được chữ ở 154 khung (bản màu bắt được 149), còn ở khung không có chữ thì điểm
cao nhất là 0,55, dưới ngưỡng 0,6. Mỗi khung tốn khoảng 9 ms. Chữ chỉ cho biết
*con nào*; chỗ ném lấy từ thân hình của nó (phần khác với sân trống), bám từ khung
này sang khung khác, đo vận tốc từ chính đường đi của nó (khớp đường thẳng, giới
hạn 40–200 px/s) và ném đón trước 0,4 giây, vì đậu bay mất một lúc mà con vật vẫn
đi sang trái. Trước đây là 0,8 giây với mức trần 300 px/s: khi khối hình dính vào
con đi trước, vận tốc bị phóng đại và cả loạt đậu rơi trúng con đi trước (chữ
"Miss" hiện trên con đó). Trong lúc bám thì không ném
con nào khác, và ném nhanh nhất game cho (0,3 giây một lần). Hai luật giữ cho
việc bám khỏi trượt sang con khác: thân hình phải ở gần chữ (hoặc gần chỗ dự
đoán), và không được lùi sang phải quá 40 px, vì ai cũng đi sang trái, nên hình
bên phải là con đi sau. Mất dấu quá 1,5 giây thì quay lại ném dàn đều.

Đo trên giả lập: ném dàn đều trúng quỷ vương 7/20 vòng, thêm phần bám thì 8/16
vòng (18 ô quỷ vương). Đón trước 0,4 / 0,8 / 1,2 giây chưa thấy khác nhau rõ.

**Con bay mang nhãn "Assist Up" / "Chance Up" / "Got Beans".** Nhãn treo bên dưới
con bay; tool so ảnh màu (`assistUp.png`, `chanceUp.png`, `gotBeans.png`): nhãn đạt
từ 0,9 trở lên, còn sân khấu tối đa 0,6 với Assist Up và 0,8 với Got Beans. Chance Up
cùng màu xanh với Assist Up nhưng tách được nhờ chữ: trên 1121 khung chạy thật, nhãn
Chance Up đạt trên 0,9, mọi chỗ khác dưới 0,6, và không lần nào hai loại bị nhận
lẫn. Tìm trước ở nửa độ phân giải rồi so lại ở độ phân giải đầy đủ quanh chỗ tìm
được, mất khoảng 18 ms cho cả ba loại. Tool ném vào thân con bay (cao hơn nhãn 90 px,
đón trước 30 px).

- Assist Up, Chance Up: mỗi loại tối đa 2 lần một vòng, cách nhau 1 giây; quỷ vương
  được ưu tiên hơn.
- Got Beans: ném liên tục, cách nhau 0,6 giây, đến khi con bay biến mất (trúng là
  nó rời màn hình, đậu +40), tối đa 15 lần một vòng. Lý do: chạy thật, một lần
  trượt là tool bỏ luôn, mất 40 đậu. Khi quỷ vương đang được bám, Got Beans và quỷ
  vương chia nhau, mỗi bên một lượt ném.

**Lời mời Wanted Quest giữa vòng.** Lời mời của người chơi khác có thể hiện lên
khi đang ném và nằm che sân khấu: chạy thật, nó che quỷ vương suốt một vòng nên
tool không thấy huy hiệu "Picked" lần nào. Vòng ném giờ cũng tìm lời mời (mỗi giây
một lần, vì mỗi lần tìm tốn 30–60 ms) và trả lời theo cài đặt chung như ở ngoài vòng.

Đo thật (10 vòng, 15/11): trúng Assist Up thì chữ "Assist Up" hiện ở góc trên, trúng
Got Beans thì đậu tăng 240 → 280. Chưa thấy Assist Up hay Chance Up làm quỷ vương
SSR/SP dễ trúng hơn: vòng 4 có cả hai mà 48 lần ném vẫn "Miss".

Lý do: ba quỷ vương SSR/SP đã chơi bị ném 9, 43 và 24 lần mà không lần nào trúng
("Miss"), trong khi quỷ vương thường trúng 6/8 vòng.

**Freeze không phải hết vòng.** Freeze giữ cả đoàn đứng yên khoảng 9 giây và phủ
một lớp băng cố định lên mép màn hình, che cả thanh đậu lẫn thanh nút phía
trên. Mẫu `inRound.png` tụt xuống 0,71 dưới lớp băng, trong khi màn chọn quỷ
vương cũng đạt 0,67, nên không ngưỡng nào tách được hai màn này. Trước đây tool
tưởng vòng đã hết, ngừng ném đúng lúc dễ trúng nhất rồi học lại nền khi cả
đoàn đang đứng trong đó. Mà Freeze xảy ra gần như vòng nào cũng có. Mẫu
`inRoundFrozen.png` cắt từ chính lớp băng: đạt 1,00 ở cả ba lần Freeze đã chụp,
và tối đa 0,74 ở mọi màn khác.

**Start không ăn thì chỉ bấm lại Start.** Con đã chọn sáng màu lên, không còn là
bóng đen. Nếu đo lại, tool sẽ bỏ qua nó và chọn đè một con nhỏ hơn: thực tế đã
có lần một con 1,6x bị đổi thành con 0,7x.

**Đổi lượt** (đã bỏ khỏi giao diện từ 2026-11-15 vì người dùng khó hiểu ngưỡng; tool luôn chơi mọi màn chọn, code đổi lượt vẫn giữ trong worker). Mảnh
SSR/SP chỉ đến từ quỷ vương SSR/SP, mà chỉ khoảng 1/16 số màn chọn có SSR/SP.
Khi có, nó thường to hơn hẳn: trong 13 lần SSR/SP xuất hiện trên 205 màn đã gán
nhãn, 9 lần được chọn và có cỡ từ 1,5 đến 3,7 lần cỡ thường, phần lớn trên 1,8.
Nên màn chọn nào có bóng to nhất dưới ngưỡng thì bấm Back, OK ở hộp "pass won't
be returned", ra thị trấn bấm biển Demon Parade để vào lại. Bản PC là đèn lồng
treo, BlueStacks là tấm bảng gỗ; đèn lồng đung đưa nên chỉ đạt 0,73–1,00, còn ở
màn khác thì tối đa 0,46. Thị trấn cũng thoáng hiện giữa các vòng bình thường,
nên chỉ bấm biển khi vừa đổi lượt. Mỗi lần đổi mất một vé và khoảng 12 giây
(chơi một vòng mất hơn một phút).

| ngưỡng | màn được chơi | SSR/SP còn giữ | quỷ vương SSR/SP mỗi giờ | vé mỗi giờ |
|---|---|---|---|---|
| tắt | 100% | 9/13 | 2,0 | 45 |
| 1,5x | 51% | 9/13 | 3,3 | 75 |
| 1,8x | 18% | 8/13 | 5,3 | 135 |
| 2,0x | 11% | 7/13 | 5,6 | 164 |

Bảng này ước lượng trên 205 màn đã gán nhãn, giả định một vòng chơi mất 80 giây và
một lần đổi mất 15 giây.

Trên Steam, kích thước đáng tin kém hơn. Hai đợt test có tổng cộng 137 màn chọn, trong
đó 14 màn có SSR/SP. Con SSR/SP to từ 0,6 đến 3,8 lần cỡ thường, còn con thường mang
đồ to (tượng cáo, tủ gỗ, ếch khổng lồ) lên tới 1,9–2,8. Ngưỡng 1,8 đã bỏ 6 màn có
SSR/SP. Gộp cả hai đợt, đổi lượt ở 1,8x chỉ tốt hơn không đổi chừng 1,6 lần (khoảng
5,2 so với 3,3 quỷ vương SSR/SP mỗi giờ).

**Nhận mặt SSR/SP đã biết** (`parade_rare.py`). Chỉ chạy khi đổi lượt, nên hiện không dùng. Khi bật đổi lượt, tool bấm thử cả ba
con cho sáng màu (mất thêm khoảng 4 giây), rồi so từng con với thư viện ảnh SSR/SP
đã sáng màu, theo từng cột. Cách so là đối chiếu từng điểm ảnh trong phạm vi bóng,
cho lệch 20 px. Kết quả đo:

- Cùng một con ở cùng cột: 0,72–0,99 (89 cặp trên Steam), và 0,85 giữa giả lập với Steam.
- 848 con thường so với mọi ảnh SSR/SP: tối đa 0,69.

Ngưỡng nhận là 0,78. Khớp thì chọn con đó và chơi, dù nó nhỏ; không khớp thì xét theo
kích thước như trên. Thư viện nằm ở `screenshots/DemonParade/rare/` (19 ảnh ban đầu),
cộng thêm `cache/parade-rare/`. Mọi con đã bấm sáng đều được lưu vào
`cache/parade-pick/`; con nào là SSR/SP thì chuyển file sang `cache/parade-rare/`. Tên
file (`…_c<cột>_x<trái>_y<trên>.png`) giữ vị trí, còn kênh alpha là bóng của con đó.

**Đếm** (`parade_results.boss_cards`). Ô mảnh của quỷ vương có dấu "Pick" ở góc
trên bên phải; một vòng có thể có hai ô nếu quỷ vương đi qua hai lần. Dấu này đạt
0,96–0,98 trên ô quỷ vương, chỗ khác tối đa 0,49. Log mỗi vòng ghi
`… — boss cards: n, SSR/SP: k`, thông báo cuối có `quỷ vương: n`.

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

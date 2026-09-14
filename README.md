# Onmyoji Tool

Ứng dụng desktop cho game **Onmyoji** trên PC, **một cửa sổ duy nhất** với các
trang chọn từ cột trái:

- **Trung tâm tác vụ** — chạy auto trên **nhiều cửa sổ game cùng lúc**: Phá Kết
  Giới, Ném đậu (Demon Parade), Thám hiểm chương, Phụ bản ngự hồn, và Event.
- **Bách khoa** — tra cứu Thức thần, Ngự hồn, Hiệu ứng. Chạy offline hoàn toàn,
  đồng bộ nội dung mới từ Supabase khi cần.

Bot chạy **nền**: không chiếm chuột, không cần cửa sổ game ở foreground. Bạn vẫn
dùng máy bình thường trong lúc nó chạy.

Giao diện dựng theo bộ design **Classical** (Claude Design): nền tối, accent
vàng đồng, chữ serif Cormorant Garamond + Lora, nhãn IBM Plex Mono.

---

## Tải về

Bản mới nhất ở trang [**Releases**](https://github.com/Long173/onmyoji-auto-releases/releases/latest)
— tải file `OnmyojiTool-<phiên bản>.zip`.

Giải nén rồi chạy `Onmyoji Tool.exe` **bên trong thư mục** — đừng lôi riêng file
exe ra, nó cần `_internal/` nằm cạnh. Không cần cài Python hay gì thêm.

App tự kiểm tra bản mới mỗi lần khởi động: có bản mới thì hiện một dải trên đầu
cửa sổ, bấm **Cập nhật** rồi **Khởi động lại để cài**. Không cần quay lại đây.

### Windows báo "Windows protected your PC"

File chưa mua chữ ký số nên SmartScreen cảnh báo. Bấm **More info** →
**Run anyway**.

### Phần mềm diệt virus báo nhầm

Một vài phần mềm diệt virus sẽ gắn cờ file này. Đó là báo nhầm, và lý do khá
dễ hiểu:

- App **tự bấm chuột vào cửa sổ game**, **chụp ảnh cửa sổ game** liên tục để
  nhận diện màn hình, **bắt phím F1/F2** kể cả khi app không được chọn, và **tự
  tải bản mới về thay chính nó**. Đó đúng là danh sách tính năng bạn thấy trên
  màn hình — nhưng cũng đúng là danh sách hành vi của một con trojan điều khiển
  từ xa, và máy quét tự động không phân biệt được hai thứ đó.
- App đóng gói bằng **PyInstaller**, công cụ mà nhiều mã độc viết bằng Python
  cũng dùng, nên phần vỏ bị nhận nhầm theo.
- File **chưa được ký số** nên Windows coi nó là phần mềm vô danh.

Cách đọc kết quả quét cho đúng: nhìn xem **hãng nào** gắn cờ và **nhãn gì**. Mã
độc thật bị 30-50 hãng bắt và các hãng gọi tên giống nhau. Vài hãng lẻ mỗi hãng
đoán một kiểu, kèm nhãn máy học như `!ml` hay `Malicious`, là hình dạng đặc
trưng của báo nhầm.

Tự kiểm chứng được hai cách. Mã nguồn nằm ngay trong repo này — đọc, hoặc tự
build lấy. Và mỗi release có file `latest-v2.json` đính kèm ghi mã **SHA-256**
của bản đó; đối chiếu bằng PowerShell:

```powershell
Get-FileHash "Onmyoji Tool.exe" -Algorithm SHA256
```

Khớp nghĩa là file bạn tải đúng là file được phát hành, không bị ai chèn thêm
gì trên đường truyền. Không khớp thì đừng chạy, và báo cho mình.

Nếu vẫn chưa yên tâm thì đừng chạy — hoàn toàn hợp lý, mình không phiền. Còn
muốn dùng thì thêm ngoại lệ cho riêng thư mục app trong Windows Security, đừng
tắt hẳn phần mềm diệt virus.

## Giấy phép

**Tool này miễn phí. Nếu bạn phải trả tiền cho ai để có nó thì bạn đã bị lừa.**

Được dùng và chia sẻ lại thoải mái, nhưng không được dùng cho mục đích thương
mại — không bán, không cho thuê, không gói kèm dịch vụ có thu phí. Giấy phép đầy
đủ: [PolyForm Noncommercial 1.0.0](LICENSE).

Thấy hay thì cho mình 1 sao nha <3

---

Phần còn lại của tài liệu này dành cho người muốn tự build hoặc sửa app.

## Chạy nhanh

```
1. Mở game, vào màn hình Phá Kết Giới, set sẵn đội hình.
2. Double-click  Launch.vbs
3. Bấm "Quét cửa sổ" -> mỗi cửa sổ game hiện thành một dòng
4. Mở "Phá Kết Giới" ở cột trái -> chọn vị trí target -> "Bắt đầu tác vụ này"
```

| File                     | Dùng khi                                                    |
| ------------------------ | ----------------------------------------------------------- |
| `Launch.vbs`             | Chạy bình thường — không hiện cửa sổ terminal                |
| `Launch (Show Log).bat`  | Khi có lỗi — hiện log trực tiếp, bật chế độ chi tiết (`-v`)  |

Log ghi vào `logs/onmyoji_auto.log`, tự xoay vòng ở 5 MB (giữ 3 file cũ).

## Cài đặt

Cần Python 3.10+ trên Windows.

```bash
pip install -r requirements.txt
```

## Đóng gói thành .exe

Để đưa cho người khác dùng mà họ không cần cài Python:

```bash
pip install pyinstaller
python tools/export_icon.py          # nếu chưa có assets/icon.ico
pyinstaller onmyoji_auto.spec --noconfirm
```

Ra `dist/Onmyoji Tool/` — **một thư mục, 245 MB, 1895 file**:

```text
Onmyoji Tool\
    Onmyoji Tool.exe     4.9 MB
    _internal\           thư viện, font, ảnh mẫu, dữ liệu wiki
```

`tools/publish_release.py` nén thư mục này thành `.zip` (~103 MB) để phát hành.

(Tên file spec vẫn là `onmyoji_auto.spec` — chỉ exe mang tên mới.)

### Vì sao là one-dir chứ không phải một file duy nhất

Bản một-file trước đây phải bung ~240 MB ra `%TEMP%\_MEIxxxxxx` **mỗi lần chạy**
rồi mới nạp `python312.dll` từ đó. Một máy người dùng đã gặp:

```text
Failed to load Python DLL '...\_MEI174516\python312.dll'
```

Chữ số cuối trong tên thư mục là **số lần bootloader thử lại**. Máy khoẻ luôn ra
đuôi `2` — thành công ngay lần đầu; `6` nghĩa là đã thất bại năm lần trước đó.
Ổ đầy, `%TEMP%` đọng đầy thư mục `_MEI` cũ, hoặc antivirus xoá DLL vừa ghi ra
đều cho ra lỗi này.

One-dir không có bước bung nào: DLL nằm sẵn trên đĩa. Đã đo sau khi đổi:
**không sinh thêm một thư mục `_MEI` nào**, và khởi động ổn định ~0.8 giây
(bản một-file dao động, có lần 3.6 giây).

Rác cũ đọng thật — đo trên máy dev: **18 thư mục, 4.3 GB**. Dọn bằng
`tools/fix_temp.bat`.

Trong `_internal/` có sẵn: font, ảnh mẫu nhận diện, và **toàn bộ dữ liệu wiki**
(287 thức thần / 64 ngự hồn / 83 hiệu ứng + 13 MB ảnh). Máy nhận không cần
checkout `onmyoji_wiki`.

### Người nhận cần biết

- **Chạy được ngay**, không cài gì thêm. Giải nén rồi chạy `Onmyoji Tool.exe`
  bên trong thư mục — **đừng lôi riêng file exe ra**, nó cần `_internal/` nằm
  cạnh. Lần đầu chạy app tự tạo `logs/` và `cache/` trong thư mục đó.
- **Windows SmartScreen sẽ cảnh báo** vì file chưa ký số — bấm *More info* →
  *Run anyway*. Một số phần mềm diệt virus cũng có thể báo nhầm: app dùng
  `PostMessage` để gửi click, kiểu hành vi đó hay bị chấm điểm nghi ngờ.
  Không dùng UPX nén chính vì lý do này.
- **Wiki hoạt động offline sẵn.** Muốn đồng bộ nội dung mới từ Supabase thì đặt
  file `.env` cạnh exe với `SUPABASE_URL` và `SUPABASE_ANON_KEY`, hoặc nhập
  trong app khi bấm Đồng bộ.
- Đặt exe ở thư mục ghi được (Desktop, Documents…). Nếu để trong `Program
  Files`, app tự chuyển log và cache sang `%LOCALAPPDATA%\OnmyojiAuto`.

### Thông tin liên hệ

Khai ở **một chỗ duy nhất** — `decompiled/source/contact.py`:

```python
CONTACTS = (
    ("Facebook", "fb.com/ten-cua-ban"),
    ("Zalo", "0900 000 000"),
)
```

Từ đó nó hiện ra hai nơi: khối **Liên hệ** cuối hộp *Cài đặt chung* (F9), và
phần cuối phần mô tả của **mọi release** trên GitHub — mọi release chứ không
chỉ bản mới nhất, vì link release là link vĩnh viễn, ai mở một tag cũ vẫn cần
biết hỏi ai.

Để trống thì cả hai nơi **không hiện gì cả**, chứ không hiện tiêu đề rỗng hay
một số điện thoại trắng. Mục nào bỏ trống thì mục đó bị bỏ qua.

Lưu ý: nội dung ở đây là **công khai** — repo release là trang GitHub public, và
file exe thì ai cầm cũng đọc được. Chỉ điền thứ bạn dám dán lên tường.

## Cập nhật trong app

Bản đóng gói tự kiểm tra bản mới lúc khởi động. Có bản mới thì hiện một dải
trên đầu: *"Có bản mới 2.2"* → bấm **Cập nhật** → tải (hiện % trên nút) →
**Khởi động lại để cài**. App tự thay chính nó rồi mở lại.

### Cách phát hành bản mới

Bản phát hành nằm trên **GitHub Releases**: file trong release của một repo
public tải được mà không cần đăng nhập, và không vướng giới hạn dung lượng mỗi
file như Supabase Storage — file .exe đang ~102 MB.

Nơi phát hành: **https://github.com/Long173/onmyoji-auto-releases** — chính là
repo này. Trước đây mã nguồn nằm riêng ở một repo private; từ 3.15 hai bên gộp
làm một, nhưng **release vẫn ở nguyên chỗ cũ**: mọi bản đã cài ngoài kia hỏi
bản mới ở đúng địa chỉ này, và địa chỉ đó đã nung vào exe lúc build nên không
sửa lại được. Đổi tên hay dời repo là những bản cài đó mất tính năng cập nhật.

Cấu hình nằm ở `decompiled/source/updater.py`:

```python
GITHUB_OWNER = "Long173"                # để trống = tắt hẳn tính năng cập nhật
GITHUB_REPO = "onmyoji-auto-releases"
```

Địa chỉ manifest tự dựng từ hai dòng đó, nên chỉ có một chỗ để sửa:

```
https://github.com/<owner>/<repo>/releases/latest/download/latest.json
```

Phải điền **trước khi build** bản đem đi đưa — exe không có cách nào khác để
biết tìm cập nhật ở đâu.

Muốn dùng `--upload` thì cần một token có quyền ghi **Contents** của repo đó
(https://github.com/settings/tokens), đặt là `GITHUB_TOKEN` trong `.env` hoặc
biến môi trường. Chỉ cần đúng quyền đó — đừng dùng token classic full scope.

**Mỗi lần ra bản mới:**

```bash
# 1. tăng APP_VERSION trong decompiled/source/theme.py
# 2. build
pyinstaller onmyoji_auto.spec --noconfirm
# 3. phát hành
python tools/publish_release.py 2.2 --notes "Sửa nhận diện hết vé" --upload
```

Bước 3 tạo release `v2.2`, đính kèm `OnmyojiTool-2.2.zip` **trước**, rồi mới
ghi manifest từ đúng địa chỉ GitHub trả về — nên manifest không bao giờ trỏ vào
file chưa có, và cũng không trỏ vào tên đoán mò (GitHub tự đổi khoảng trắng
trong tên asset thành dấu chấm). Sau đó nó ghi `CHANGELOG.md` lên gốc repo.

Bỏ `--upload` thì nó chỉ chuẩn bị ba file trong `dist/release/` để tự tạo
release bằng tay trên web.

Release **không được để ở dạng draft** — `releases/latest/` bỏ qua draft, app
sẽ không thấy gì. Script đã đặt sẵn `draft: false`.

### Trong zip chỉ có thứ PyInstaller sinh ra

`stage()` chỉ nén `Onmyoji Tool.exe` và `_internal/`. Mọi thứ khác trong
`dist/Onmyoji Tool/` là do **chạy thử** bản build mà có.

Đây không phải chuyện sạch sẽ hình thức. Lần diễn tập cập nhật đầu tiên cho
thấy nén cả thư mục thì nhật ký của máy build **ghi đè nhật ký của người dùng**
— và nếu máy build có `.env` cạnh exe thì khoá Supabase sẽ được nén và **phát
hành công khai**. Giờ chạy `stage()` in ra những gì nó bỏ qua.

### Hai manifest, và vì sao

| File | Ai đọc | Nội dung |
|---|---|---|
| `latest-v2.json` | bản 3.1 trở đi | bản mới nhất, trỏ vào `.zip` |
| `latest.json` | bản 3.0 trở về trước | **đóng băng ở 3.0** vĩnh viễn |

Bản 3.0 trở về trước là one-file: chúng đọc `latest.json`, tải thứ nó trỏ tới
rồi **đổi tên thành `.exe` và chạy**. Đưa cho chúng file `.zip` là mọi bản cài
đó chết ngay lần mở sau. Code của chúng đã nằm ngoài kia, không sửa được.

Nên `latest.json` được phát hành lại y nguyên cùng mọi release, mãi mãi mô tả
bản 3.0. Bản cũ đọc nó, thấy không có gì mới hơn, và im lặng thay vì tự huỷ.
Ai còn ở 2.x thì được mời lên 3.0 — vẫn là exe one-file thật, vẫn chạy được.

Cái giá: **bản cài trước 3.1 không tự cập nhật được nữa**, phải thay tay một
lần. Hướng dẫn nằm trong `CHANGELOG.md`.

### Cơ chế thay bản mới

Windows khoá file .exe đang chạy nên app không tự ghi đè được. Nó tải `.zip`
thành `update.zip` cạnh exe, rồi bàn giao cho một script PowerShell: script đợi
tiến trình thoát → giải nén → thay → mở lại app → tự xoá.

Thư mục app chứa cả **thứ của app** lẫn **thứ của người dùng**:

```text
Onmyoji Tool\
    Onmyoji Tool.exe     thay
    _internal\           thay
    logs\ cache\ .env wiki\    giữ nguyên
```

Nên script **không** xoá sạch thư mục rồi bung đè lên. Nó chỉ chép vào đúng
những mục có trong zip, và mỗi mục sắp bị đè đều được chuyển vào
`.update-backup` trước. Hỏng giữa chừng — file bị khoá, ổ đầy, zip đứt — thì
backup được trả về chỗ cũ và **bản cũ được mở lại**. Thay một thư mục có nhiều
cách hỏng nửa chừng hơn hẳn đổi tên một file, mà app hỏng nửa chừng là app
không bao giờ mở lại được.

Phần này có test chạy PowerShell thật trên một bản cài giả, gồm cả trường hợp
hỏng giữa chừng (dùng một tiến trình giữ `_internal/` làm thư mục làm việc, đúng
kiểu antivirus hay Explorer giữ file). Khẳng định quan trọng nhất: **sau khi
cập nhật thất bại, exe cũ vẫn còn nguyên chỗ cũ.**

Một lỗi đã bị chính test đó bắt: `.update-backup` được tạo *trước* vòng lặp, nên
hỏng ngay ở mục đầu tiên sẽ để lại thư mục rỗng — nhánh dọn dẹp lúc đó còn bị
chặn bởi một cờ `$moved` thừa.

Dùng PowerShell chứ không phải `.bat` vì cmd xử lý đường dẫn không phải ASCII
rất tệ, mà app này hay nằm trong thư mục kiểu `陰陽師Onmyoji`.

### Giới hạn cần biết

File tải về được **đối chiếu SHA-256** với manifest, nên hỏng hoặc đứt giữa
chừng là bị bỏ. Nhưng **không có chữ ký số**: manifest là nguồn tin duy nhất,
nên ai ghi được vào release đó thì chạy được code trên máy mọi người đã cài.
Giữ quyền ghi vào repo đó — và cái token — chặt như giữ chính app.

Repo chứa release phải là **public**. Release của repo private cần đăng nhập
mới tải được, nên app của người khác sẽ tải hỏng; `publish_release.py` kiểm tra
điều này và từ chối trước khi upload.

Cập nhật chỉ bật ở bản đóng gói và khi `GITHUB_OWNER` đã điền — chạy từ source
thì tính năng này tắt.

### Lỗi "Failed to load Python DLL ... \_MEIxxxxxx\python312.dll"

Xảy ra sau khi cập nhật, lúc exe mới khởi động. **Không phải file tải hỏng** —
file tải về đã đối chiếu SHA-256, sai là bị bỏ chứ không chạy.

Nguyên nhân nằm ở kiểu đóng gói **one-file**: mọi thứ nhét trong một exe, nên
mỗi lần chạy bootloader phải bung ~240 MB ra `%TEMP%\_MEIxxxxxx` rồi mới nạp
`python312.dll` từ đó. Bung hỏng thì báo đúng dòng lỗi trên.

Đọc được tên thư mục: nó là `_MEI` + PID + **số lần thử**. Máy chạy tốt luôn ra
đuôi `2` (`_MEI195362`, `_MEI283402`) — lần thử đầu đã tạo được. Gặp đuôi lớn
hơn, ví dụ `_MEI174516`, tức là bootloader phải thử lại nhiều lần mới tạo nổi
thư mục: ổ đĩa hết chỗ, hoặc `%TEMP%` đầy thư mục `_MEI` cũ.

Rác này tích thật: đo trên máy dev thấy **18 thư mục, 4.3 GB**, mỗi lần bị
force-kill lại để lại 240 MB. Thoát app bình thường thì bootloader tự dọn, nên
thủ phạm là những lần `taskkill /F` lúc phát triển.

Cách sửa cho người dùng: chạy **`tools\fix_temp.bat`** (đóng app trước). Nó xoá
các thư mục `_MEI` cũ, bỏ qua thư mục đang được dùng, rồi báo dung lượng còn
trống và cảnh báo nếu dưới 3 GB.

Vẫn lỗi sau khi dọn thì gần như chắc là **phần mềm diệt virus đã xoá
`python312.dll`** khỏi thư mục vừa bung. Exe mới tải về, chưa ký số, là đúng
kiểu file bị chấm nghi ngờ. Khôi phục từ Quarantine rồi thêm vào loại trừ.

Muốn diệt tận gốc thì phải bỏ one-file, đóng gói kiểu **one-dir** — không bung
gì lúc chạy, khởi động nhanh hơn hẳn, không đụng `%TEMP%`. Đổi lại phải phát
hành cả thư mục (zip) và updater phải thay được thư mục chứ không chỉ một file.

### Đọc bảng kết quả Ném đậu: tên và số mảnh

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

### Ném vào con hiếm: nhận dạng bằng màu

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

### Máy tự gán nhãn con thường

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

### Muốn cập nhật dữ liệu wiki mà không build lại

Tạo thư mục `wiki\assets\data` (và `wiki\assets\images`) cạnh exe — app ưu tiên
dữ liệu ở đó hơn bản nhúng trong file.

---

## Trung tâm tác vụ

Giao diện chia hai trục: **cửa sổ game** và **tác vụ auto**.

- Cột trái liệt kê mọi tác vụ. Chấm sáng nghĩa là đang có cửa sổ chạy tác vụ đó.
- **Bảng điều khiển** cho cái nhìn tổng: mỗi dòng là một cửa sổ game với *chuỗi
  tác vụ* của nó. Chip đầu chuỗi (có dấu `▸`) là tác vụ sẽ chạy.
- Mở một tác vụ ra được trang riêng: cấu hình bên trái, các cửa sổ đang gán tác
  vụ đó bên phải, kèm nút gán thêm. Mỗi thẻ có **ảnh trực tiếp của cửa sổ game**.

### Ảnh trực tiếp (thumbnail)

Chỉ có trên trang tác vụ, không có ở bảng tổng quan — bảng cần gọn để nhìn hết
nhiều cửa sổ một lúc.

Cách tiết chế chi phí, vì mỗi lần chụp một cửa sổ rảnh là một lần gọi GDI thật:

| Tình huống | Chi phí |
| --- | --- |
| Cửa sổ **đang chạy** | Miễn phí — đọc lại khung hình vòng lặp vừa chụp |
| Cửa sổ **rảnh**, đang xem trang đó | Chụp thật, **cách 1 giây một lần** |
| Trang tác vụ **không mở** | Không chụp gì |
| Đang ở bảng tổng quan | Không chụp gì |

Rời trang tác vụ là app nhả device context của các cửa sổ rảnh.

| Thành phần | Ý nghĩa |
| --- | --- |
| **Quét cửa sổ** | Tìm lại cửa sổ game đang mở. Giữ nguyên tác vụ đã chọn và worker đang chạy. Bỏ qua Explorer/trình duyệt và chính app này dù tiêu đề có chữ "Onmyoji" |
| **Bắt đầu tất cả** | Ở trang chủ: chạy mọi cửa sổ. Ở trang một tác vụ: chỉ chạy cửa sổ **đang đặt** tác vụ đó — không kéo cửa sổ đang làm việc khác sang |
| **→ tên cửa sổ** | Chuyển cửa sổ đó sang tác vụ của trang đang mở. Lựa chọn được nhớ theo **tiêu đề cửa sổ** |
| **Nhật ký chạy** | Mở thư mục log |
| **Cài đặt chung / F9** | Thiết lập đúng cho **mọi** tác vụ: lời mời truy, thông báo khi xong |
| **F1 / F2** | Tạm dừng-tiếp tục / kết thúc tất cả |

Trạng thái: `Sẵn sàng` · `Đang chạy` (chấm vàng nhấp nháy) · `Tạm dừng` ·
`Hết vé` · `Mất cửa sổ`.

### Thêm một tác vụ mới

Toàn bộ giao diện đọc từ **`tasks.py`**. Thêm một automation = thêm một
`TaskSpec` ở đó, không đụng file UI nào:

```python
TaskSpec(
    id="beans",
    name="Ném đậu",
    kicker="Tác vụ · Đậu Ma",
    summary="Ném đậu cho toàn bộ bạn bè trong danh sách.",
    progress_label="lượt đã ném",
    fields=(
        Field("count", SEGMENTED, "Số lượt mỗi ngày", ("30", "60", "Tối đa"), "60"),
        Field("close_when_done", TOGGLE, "Đóng bảng khi xong", default=True),
        Field("", NOTE, "Giải thích gì đó cho người dùng."),
    ),
    build=build_beans,     # (hwnd, control, config, on_finished, on_error) -> worker
)
```

Từ một khai báo như trên, app tự có: dòng ở cột trái, trang riêng, bảng cấu
hình sinh từ `fields`, lưu/đọc thiết lập, gán cửa sổ, và nút bắt đầu/kết thúc.

**Hai tầng thiết lập**, cùng dùng chung `Field` nên cùng được sinh control:

| Tầng | Ở đâu | Dùng khi |
| --- | --- | --- |
| `tasks.APP_FIELDS` | Cài đặt chung (F9) | Đúng cho mọi tác vụ — ví dụ lời mời truy, vì hộp thoại đó chặn bất kỳ tác vụ nào |
| `TaskSpec.fields` | Trang của tác vụ | Chỉ tác vụ đó hiểu — ví dụ vị trí target |

Worker nhận **tầng app, chồng tầng task lên trên** (`tasks.merge_layers`), nên
`build` chỉ cần đọc `config[key]` mà không cần biết nó từ tầng nào. Key của task
không được trùng key của app — có test chặn, vì trùng là tầng task âm thầm che
tầng app và không nhìn ra được từ giao diện.

`build` nhận config rồi trả về một **worker** — bất kỳ object nào có:

```
start()  stop()  join(timeout)  is_alive()
pause()  resume()  is_paused
progress        -> int    số việc đã làm, nhãn lấy từ progress_label
elapsed_seconds -> float  thời gian chạy, không tính lúc tạm dừng
latest_frame()  -> khung hình hoặc None
```

`realm_raid.RealmRaidWorker` là bản mẫu.

**Tác vụ khai báo mà chưa có `build`** vẫn hiện trong giao diện nhưng **không
bắt đầu được** — nút bị khoá, bảng cấu hình thay bằng ghi chú `todo` nói cần gì
để làm nó. Ba tác vụ ngoài Phá Kết Giới hiện đang ở trạng thái này: chúng là
chỗ trống có chủ ý, không phải tính năng hỏng.

### Một cửa sổ, một tác vụ

Mỗi cửa sổ chạy **đúng một** tác vụ do bạn chọn. Xong thì dừng ở trạng thái hoàn
thành — app không tự chuyển sang tác vụ khác.

Trước đây mỗi cửa sổ giữ một **danh sách** và tự chạy tiếp mục kế tiếp khi xong.
Đã bỏ, vì không ai xâu chuỗi tác vụ cả — người ta mở đúng phần mình cần rồi
chạy. Cái chuỗi đó còn gây một lỗi khó chịu: bấm **Bắt đầu** ngay trên trang Ném
đậu lại khởi động Phá Kết Giới, và trang Ném đậu hiện `Trong hàng chờ`.

Cấu hình cũ **không mất**: file thiết lập do bản trước ghi ra là một danh sách,
và app đọc mục đầu tiên còn tồn tại làm tác vụ của cửa sổ đó.

**Lựa chọn được nhớ theo tiêu đề cửa sổ**, vì handle đổi mỗi lần mở game. Nhiều
cửa sổ Onmyoji thường trùng tiêu đề (`陰陽師Onmyoji`), nên chúng dùng chung một
lựa chọn đã lưu. Đây là đánh đổi có ý thức: tiêu đề là thứ duy nhất còn nguyên
qua các lần khởi động. Muốn mỗi acc một lựa chọn riêng thì đổi tên cửa sổ.

Thiết lập của tác vụ (ví dụ vị trí target) thì **dùng chung cho mọi cửa sổ** —
đổi một lần là đổi cho tất cả.

### Nâng cấp từ v2

Lần chạy đầu của v3 tự chuyển thiết lập cũ sang: vị trí target trong `slots/` và
lựa chọn lời mời truy đi vào `tasks/realm_raid/...`, rồi xoá các khoá v2 đã chết
(`vitri`, `refresh`, `slot`, `window_title`). Không mất thiết lập nào.

### Đổi tên: "Onmyoji Auto" → "Onmyoji Tool"

Đổi **tên hiển thị**: tiêu đề cửa sổ, nhãn ở cột trái, thông báo, tên exe
(`Onmyoji Tool.exe`), tên file phát hành (`OnmyojiTool-X.Y.exe`). Tất cả lấy từ
`theme.APP_NAME` — một chỗ duy nhất.

**Không đổi** mấy thứ sau, vì chúng là *địa chỉ dữ liệu* chứ không phải nhãn:

| Giữ nguyên | Nếu đổi thì sao |
| --- | --- |
| `theme.ORGANISATION` / `SETTINGS_SCOPE` → `HKCU\Software\OnmyojiAuto\RealmRaid` | App trỏ vào khoá rỗng: mất sạch thiết lập và tác vụ đã chọn |
| `%LOCALAPPDATA%\OnmyojiAuto` | Log và cache wiki cũ bị bỏ lại, wiki phải tải lại ảnh |
| `APP_USER_MODEL_ID` | Windows bỏ ghim taskbar và mất lịch sử thông báo |
| repo `onmyoji-auto-releases` | Bản đã phát ra ngoài phải dựa vào redirect của GitHub — mà ai tạo repo trùng tên cũ là redirect đứt |

Hai chỗ khác cố ý giữ tên cũ: `onmyoji_auto.spec` (để script build cũ còn chạy)
và `logs/onmyoji_auto.log`.

**Bản đã cài sẽ giữ tên file cũ sau khi cập nhật.** Cơ chế thay file ghi đè đúng
đường dẫn exe đang chạy, nên máy nào đang có `Onmyoji Auto.exe` thì sau cập nhật
vẫn tên đó nhưng ruột là bản mới. Muốn đúng tên thì tải lại từ Releases. Cố đổi
tên trong lúc tự cập nhật sẽ làm đứt mọi shortcut đã ghim, nên không làm.

### Icon

Icon **"Dấu Kết Giới"** theo design: khuôn kết giới hình thoi nét vàng đồng trên
nền gỗ đen. Nó xuất hiện ở cửa sổ, taskbar, khay hệ thống và trên thông báo.

Icon được **vẽ bằng vector lúc chạy** (`ui/app_icon.py`) chứ không nạp từ file
ảnh — mỗi cỡ 16/32/48/64/128/256 được vẽ riêng nên nét mảnh vẫn sắc ở 16px, và
màu không bao giờ lệch khỏi `theme.py`.

Cần file rời (đặt cho shortcut, hoặc đóng gói sau này):

```bash
python tools/export_icon.py     # -> assets/icon.ico + assets/icon-256.png
```

`.ico` chứa cả 6 cỡ, nén PNG, khoảng 25 KB. Không dùng `QImageWriter` vì nó chỉ
ghi được một ảnh 256px không nén, ra file 270 KB — Windows khi đó phải thu nhỏ
ảnh 256px cho ô taskbar 16px.

### Thông báo

Hoàn thành và lỗi đều báo qua **Notification Center của Windows**, không mở hộp
thoại. Bot chạy hàng giờ không ai trông, nên một modal đứng chắn trước mọi thứ
tới khi có người bấm là sai — và cửa sổ thứ hai xong sau đó lại chồng thêm cái
nữa. Thông báo thì vẫn còn đó lúc bạn quay lại.

Lỗi cũng đi cùng đường: thẻ của cửa sổ đó vẫn giữ trạng thái `Mất cửa sổ` nên
thông tin không mất khi thông báo tự tắt.

Kênh gửi là `QSystemTrayIcon` có sẵn trong Qt — không thêm thư viện. Vì vậy app
có một icon ở khay hệ thống trong lúc chạy; đóng app là nó biến mất. Máy nào
không có khay hệ thống thì tự động quay về hộp thoại, để không nuốt mất thông báo.

Chỉ còn **một** hộp thoại duy nhất trong app: xác nhận khi đóng lúc đang chạy.

### Đóng cửa sổ app là dừng hết

Không có auto nào sống sót sau khi app đóng. Worker là **thread trong chính
tiến trình app**, không phải tiến trình riêng, nên:

- Bấm **✕** → mọi worker được gọi `stop()`, nhả device context, rồi app thoát.
- Kill app bằng Task Manager → thread chết theo tiến trình.

Cả hai đều không để lại thứ gì còn click vào game.

Nếu **đang có cửa sổ chạy**, app hỏi lại trước khi thoát (*"Đang chạy N cửa
sổ"* → **Thoát** / **Ở lại**), nút mặc định là "Ở lại" để lỡ nhấn Enter cũng
không mất phiên farm. Không có cửa sổ nào chạy thì đóng thẳng, không hỏi.

Muốn giữ auto chạy mà không vướng cửa sổ thì **thu nhỏ**, đừng đóng.

Toàn bộ hành vi này được khoá bằng `tests/test_dashboard_lifecycle.py`.

### Vòng lặp Phá Kết Giới

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

### Phụ bản ngự hồn: nhận biết nút bằng **màu**, không phải hình

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

### Mỗi màn kết thúc có điểm bấm riêng

Một trận có **hai** màn kết thúc, và chúng không giống nhau:

| Màn | Bấm ở | Vì sao |
| --- | --- | --- |
| Victory | **(1055, 445)** | Giữa màn là cụm thức thần, hai avatar phần thưởng ở ~(680,320) và ~(790,320). Bấm vào đó **mở thứ khác** chứ không thoát — đây là lỗi làm run thật đứng lại. Góc phải dưới là nền đất trống trên mọi khung đã ghi |
| Tap to continue | (561, 316) | Bấm đâu cũng được, giữa màn là đủ |

### Đếm trận: theo **cạnh lên**, có chống dội

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

### Khi nào mới được đọc số vé

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

### Đọc số vé

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

### Lời mời truy (co-op Wanted Quest)

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

---

## Bách khoa (wiki tiếng Việt)

287 Thức thần · 64 Ngự hồn · 109 Hiệu ứng, kèm ảnh — **đọc thẳng từ checkout
`onmyoji_wiki` bên cạnh**, không cần mạng, không cần cấu hình.

**Nằm trong cửa sổ chính**, không phải cửa sổ riêng. Ba mục Thức thần / Ngự hồn /
Hiệu ứng là ba dòng ở cột trái, kèm số lượng. Trước đây wiki có cột nav riêng —
hai sidebar cạnh nhau ngốn 460px chỉ để làm nav, nên ba mục đó dọn vào sidebar
duy nhất của app.

Nút **Đồng bộ** và nguồn dữ liệu nằm trên thanh tìm kiếm của trang. Trang wiki
không có nút Bắt đầu/Dừng — băng tiêu đề tự ẩn hai nút đó.

Đang tìm kiếm thì **không mục nào sáng** ở cột trái: kết quả trải khắp ba mục
nên tô sáng một mục là nói sai.

`python decompiled/source/app.py --wiki` mở thẳng vào trang wiki.

| Tính năng      | Chi tiết                                                        |
| -------------- | ---------------------------------------------------------------- |
| Tìm kiếm       | Bỏ dấu (`dai thien cau` → **Đại Thiên Cẩu**), không phân biệt thứ tự từ, khớp cả biệt danh và tên Nhật/Anh. `Ctrl+K` để focus |
| Lọc            | Theo hạng: SP / SSR / SR / R / N                                 |
| Chi tiết thức thần | Chỉ số, kỹ năng, ngự hồn gợi ý, bị khắc chế bởi, truyền thuyết, nguồn |
| Chi tiết ngự hồn | Hiệu ứng theo số món, thức thần hay dùng                        |
| Liên kết chéo  | Bấm ngự hồn gợi ý → sang trang ngự hồn, và ngược lại              |
| `Esc`          | Quay lại danh sách                                               |

### Đồng bộ Supabase (tuỳ chọn)

Bấm **Đồng bộ lại** để kéo nội dung mới. Thứ tự tìm thông tin đăng nhập:

1. Những gì bạn nhập trong app (lưu ở QSettings)
2. `auto_ads/.env`
3. `onmyoji_wiki/.env` — dùng lại luôn cấu hình của app Flutter
4. Biến môi trường

Chưa có thì app hỏi khi bấm đồng bộ. Khoá `anon` an toàn để lưu trên máy:
`supabase/migrations/0002_rls.sql` chỉ cho nó quyền `SELECT`.

Dữ liệu đã đồng bộ nằm ở `cache/wiki/`, được ưu tiên hơn dữ liệu đóng gói ở lần
mở sau. Ảnh nào chưa có trên máy sẽ được tải từ bucket `assets` vào
`cache/images/` (tối đa 120 file mỗi lần đồng bộ).

### Hai nguồn dữ liệu không giống hệt nhau

Tính đến lần kiểm tra gần nhất:

| | Đóng gói (`onmyoji_wiki`) | Supabase |
| --- | --- | --- |
| Thức thần / Ngự hồn | 287 / 64 | 287 / 64 |
| Hiệu ứng | 83 | **109** |
| `recommended_souls` | trống | **có** |
| `name_jp` | **có, 49 bản ghi** | đã bị xoá (migration 0009) |
| Đường dẫn ảnh | `assets/images/souls/x.webp` | `souls/x.webp` |

Vì vậy `sync()` **lấp chỗ trống**: field nào server để rỗng thì lấy từ dữ liệu
đóng gói, còn field server đã có thì không bao giờ ghi đè. Hiện chỉ còn `name_jp`
cần lấp — dùng làm tên phụ trên card và cho tìm kiếm. Số field được lấp có ghi
trong log.

Muốn bỏ hẳn bước lấp này thì đổ `name_jp` lên Supabase trước — xem
`onmyoji_wiki/tools/migrate/`.

---

## Cấu trúc

```
auto_ads/
├── Launch.vbs / Launch (Show Log).bat
├── requirements.txt · .env.example
├── assets/fonts/            6 file TTF (xem tools/fetch_fonts.py)
├── screenshots/RealmRaid/   ảnh mẫu để nhận diện màn hình
├── logs/ · cache/           tự sinh
├── onmyoji_auto.spec        cấu hình đóng gói PyInstaller
├── tools/fetch_fonts.py     dựng lại assets/fonts từ google/fonts
├── tools/export_icon.py     xuất assets/icon.ico + icon-256.png
├── tools/publish_release.py tạo manifest cập nhật cho bản mới
├── tools/record_screens.py  ghi màn hình game, chỉ lưu khi đổi thật
├── tools/crop_region.py     cắt/phóng to, và cắt ảnh mẫu
├── tools/score_template.py  chấm điểm ảnh mẫu, in cách biệt khớp/trượt
├── tests/                   pytest — 427 test, không cần game
└── decompiled/
    ├── source/              code đang chạy
    └── _legacy/             bản decompile gốc (lưu trữ, không dùng)
```

| Module | Trách nhiệm |
| ------ | ----------- |
| `app.py` | Entry point, khởi tạo Qt trên main thread |
| `theme.py` · `fonts.py` | Token màu/chữ, nạp font đóng gói |
| `paths.py` · `logging_setup.py` | Định vị thư mục (checkout và bản đóng gói), logging xoay vòng |
| `geometry.py` | Toạ độ + quy đổi theo kích thước cửa sổ thật |
| `ticket_counter.py` | Đọc bộ đếm vé (tách ký tự, so chữ số đầu) |
| `game_control.py` | Chụp màn hình, cache khung hình, so template, gửi click |
| `realm_raid.py` | Vòng lặp Phá Kết Giới + các handler |
| **`tasks.py`** | **Khai báo mọi tác vụ auto — chỗ duy nhất cần sửa để thêm tính năng** |
| `app_settings.py` | Một chỗ mở QSettings, để test chuyển hướng được |
| `auto/window_scanner.py` | Liệt kê cửa sổ game đang mở |
| `auto/session.py` · `auto/manager.py` | Một cửa sổ = một session giữ tác vụ đã chọn; manager giữ tất cả và thiết lập dùng chung |
| `ui/task_sidebar.py` · `page_header.py` | Cột trái sinh từ registry, băng tiêu đề |
| `ui/home_view.py` · `task_view.py` | Trang tổng quan (bảng cửa sổ) và trang từng tác vụ |
| `ui/wiki_page.py` | Trang bách khoa, nhúng trong cửa sổ chính |
| `ui/fields.py` | Sinh control từ Field — dùng chung cho trang tác vụ và Cài đặt chung |
| `ui/preview.py` | Khung hình game → QPixmap cho thumbnail |
| `souls_dungeon.py` | Vòng lặp Phụ bản ngự hồn (chủ phòng / thành viên) |
| `wanted_invite.py` | Trả lời lời mời truy — dùng chung cho mọi tác vụ |
| `wiki/models.py` · `search.py` | Bản ghi wiki, tìm kiếm bỏ dấu |
| `wiki/repository.py` | Nạp dữ liệu offline → cache → Supabase |
| `wiki/supabase_client.py` · `config.py` | PostgREST qua urllib, tìm credentials |
| `wiki/images.py` | Định vị và cache ảnh |
| `updater.py` · `ui/update_banner.py` | Kiểm tra, tải, đối chiếu hash và tự thay file |
| `ui/app_icon.py` | Icon app "Dấu Kết Giới", vẽ vector theo design |
| `ui/notifications.py` | Thông báo Windows qua tray icon |
| `ui/` | Toàn bộ widget: chrome, primitives, controls, 2 cửa sổ, các view |

## Test

```bash
pip install pytest
python -m pytest tests -q
```

Không cần mở game và không cần mạng: `GameControl`, worker và scanner đều được
thay bằng stub, không click gì cả. Test dùng dữ liệu wiki thật sẽ tự bỏ qua nếu
không có checkout `onmyoji_wiki`.

---

## Lưu ý kỹ thuật

Những chỗ đã trả giá để tìm ra — đừng "sửa lại cho gọn":

**`cv2.imread` chết với đường dẫn Unicode.** Thư mục project tên `陰陽師Onmyoji`.
Trên Windows `imread` trả về `None` (không báo lỗi) với đường dẫn không phải
ASCII, biến "không đọc được ảnh" thành "không tìm thấy template" ở mọi khung
hình. `GameControl._read_image` đọc bytes bằng Python rồi đưa qua `cv2.imdecode`.

**Chụp màn hình dùng `PrintWindow(PW_RENDERFULLCONTENT)`**, không phải `BitBlt`.
`BitBlt` trả về ảnh cũ trên bề mặt DirectX. Click gửi bằng
`PostMessage(WM_LBUTTON*)` nên chuột thật không di chuyển và cửa sổ không cần
focus.

**Cache khung hình.** Một vòng quét so tới 14 template; trước đây mỗi lần so là
một lần chụp. Với nhiều cửa sổ, chi phí đó nhân lên. Giờ mỗi vòng chụp một lần,
ảnh xám suy ra từ ảnh màu, và cache bị huỷ sau mỗi click hoặc mỗi lần chờ — để
không bao giờ so template với khung hình trước khi click.

**Cửa sổ game được resize theo *client*, không phải kích thước ngoài.** Toạ độ
và ảnh mẫu đều ghi ở client 1122×633. `geometry.Geometry` quy đổi toạ độ cố
định sang kích thước thật, nhưng `cv2.matchTemplate` **không** co giãn ảnh mẫu
— client lệch là độ chính xác giảm.

Chỗ này từng có hằng số `TARGET_WINDOW_SIZE = (1138, 672)` — kích thước **ngoài**
để đặt. Nó đúng trên đúng một máy, vì viền cửa sổ ở đó ăn 16px ngang và 39px
dọc, trừ ra vừa đẹp 1122×633. **Viền không phải hằng số.** Ở DPI 125% nó thành
21×50, và cùng kích thước ngoài đó chỉ còn client 1117×623.

Đọc ra được từ log của một máy hỏng thật:

```text
window=1138x673 client=1117x623 border=(10,40)
```

`16×1.25≈21`, `39×1.25≈49` — đúng dấu vân tay của DPI 125%.

Giờ `resize_game_window` đo viền của chính cửa sổ đang xử lý rồi cộng vào kích
thước client mong muốn, lặp vài vòng vì game tự chỉnh lại cửa sổ sau mình để giữ
tỉ lệ khung hình. Có test mô phỏng đúng viền của cả hai máy.

Đáng nói: lệch 10px **không** phải nguyên nhân làm hỏng Phá Kết Giới — đo riêng
thì nó chỉ làm điểm khớp tụt từ 1.00 xuống 0.902. Nguyên nhân thật ở mục dưới.

**Nói chuyện với game phải ở đúng không gian toạ độ của nó.** Xem `dpi.py`.

Game không nhận biết DPI. Ở scaling 125%, Windows ảo hoá nó: game tin khung
hình của nó là 898×507 và vẽ đúng ngần ấy, còn tiến trình nhận biết DPI hỏi
Windows thì được trả lời 1122×633 — kích thước tính bằng điểm ảnh thật. Cả hai
đều đúng; trộn vào nhau thì không. Đo trên máy dev sau khi tạm đặt màn hình về
125%:

| | luồng aware | luồng unaware |
|---|---|---|
| `section.png` | 0.913 — **khớp vào nền trống** | 0.991 |
| `start.png` | 0.362 (nút đang hiện rõ) | 0.986 |
| bấm nút Attack | không có gì xảy ra | vào trận |

`PrintWindow` trả về tấm bitmap 1122×633 với nội dung game nằm ở góc trên-trái
898×507, còn lại đen. Và Windows quy đổi toạ độ trong message chuột theo DPI
của **luồng gửi** — đây là chỗ khó thấy nhất, vì code click nhìn hoàn toàn đúng.

Khớp giả 0.91 vào vùng nền còn nguy hơn khớp trượt: bot bấm vào chỗ trống, không
gì mở ra, vòng lặp đứng im mà log vẫn báo "tìm thấy quái".

`dpi.game_space()` bọc mọi thao tác đo, chụp và bấm. Chỉ luồng nói chuyện với
game đổi chế độ, nên giao diện Qt vẫn nét. Ở 100% thì hai không gian trùng nhau
và không có gì thay đổi.

Có test khoá lại điều kiện vô hình này: click **phải** được gửi từ luồng
unaware. Không test thì rất dễ bị "dọn dẹp" mất mà chẳng có gì báo lỗi.

**Layout Qt lồng nhau phải set margin.** `QVBoxLayout()` không có tham số sẽ
nhận margin mặc định 9px mỗi cạnh, cộng dồn 18px vào mỗi trục và phá vỡ spacing
của design. Dùng `ui.primitives.vbox()` / `hbox()`.

**Bản đóng gói tách hai gốc đường dẫn.** Trong checkout, mọi thứ nằm chung một
thư mục. Khi frozen, PyInstaller giải nén tài nguyên vào một thư mục tạm
chỉ-đọc (`sys._MEIPASS`), còn log/cache/`.env` phải nằm cạnh exe. `paths.py`
tách thành `BUNDLE_ROOT` (đọc) và `DATA_ROOT` (ghi) — trong checkout hai cái
trùng nhau, nên lỗi loại này chỉ lộ ra sau khi đóng gói.

**Font là bản static tự dựng.** Cormorant Garamond và Lora chỉ có bản variable;
Qt 5 chỉ đọc được instance mặc định nên weight 600 sẽ bị giả lập đậm. Hai font
đã được `fonttools` làm phẳng ở weight 400/600. Tất cả đều đủ dấu tiếng Việt.

**Dừng worker theo cơ chế hợp tác** (`threading.Event`), thoát dưới 1 giây. Bản
1.0 inject `SystemExit` vào thread — có thể trúng giữa lời gọi GDI và rò handle.

**Trường `image` có hai cách viết.** JSON đóng gói dùng đường dẫn Flutter
(`assets/images/souls/x.webp`), Supabase dùng key của bucket (`souls/x.webp`).
`ImageResolver.local_path` thử cả hai — chỉ xử lý một dạng là mất sạch ảnh ngay
khi người dùng bấm đồng bộ.

## Giới hạn

- Chỉ hỗ trợ Phá Kết Giới. Các chế độ khác (Soul, Story, Seal, Demon Parade…)
  đã bị gỡ khỏi bản này.
- Chỉ chạy trên Windows (`pywin32`, PrintWindow, PostMessage).
- Wiki cần checkout `onmyoji_wiki` nằm cạnh `auto_ads` để có dữ liệu và ảnh
  offline; không có thì phải đồng bộ từ Supabase.
- Phím tắt F1/F2 cần quyền hook toàn cục; nếu đăng ký thất bại, app ghi log và
  phím chỉ hoạt động khi cửa sổ đang được chọn.

# Đóng gói và phát hành

Build ra .exe, phát hành lên GitHub Releases, và cơ chế app tự thay chính nó.

---

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

---

[← Về trang chính](../README.md)

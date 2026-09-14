# Kiến trúc

Cấu trúc thư mục, trách nhiệm từng module, cách Trung tâm tác vụ được sinh
ra từ registry, và những quyết định về giao diện đã chốt.

---

## Cấu trúc

```
onmyoji-auto/
├── Launch.vbs / Launch (Show Log).bat
├── requirements.txt · .env.example
├── assets/fonts/            6 file TTF (xem tools/fetch_fonts.py)
├── screenshots/<Tác vụ>/    ảnh mẫu để nhận diện màn hình
├── logs/ · cache/           tự sinh
├── onmyoji_auto.spec        cấu hình đóng gói PyInstaller
├── docs/                    tài liệu chi tiết
├── tools/fetch_fonts.py     dựng lại assets/fonts từ google/fonts
├── tools/export_icon.py     xuất assets/icon.ico + icon-256.png
├── tools/publish_release.py tạo manifest cập nhật cho bản mới
├── tools/record_screens.py  ghi màn hình game, chỉ lưu khi đổi thật
├── tools/crop_region.py     cắt/phóng to, và cắt ảnh mẫu
├── tools/score_template.py  chấm điểm ảnh mẫu, in cách biệt khớp/trượt
├── tests/                   pytest, không cần game
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
để làm nó. Hiện cả năm tác vụ trong registry đều đã chạy được, nên không có mục
nào ở trạng thái này; đây là chỗ trống có chủ ý dành cho tác vụ sắp viết, không
phải tính năng hỏng.

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

## Nâng cấp từ v2

Lần chạy đầu của v3 tự chuyển thiết lập cũ sang: vị trí target trong `slots/` và
lựa chọn lời mời truy đi vào `tasks/realm_raid/...`, rồi xoá các khoá v2 đã chết
(`vitri`, `refresh`, `slot`, `window_title`). Không mất thiết lập nào.

## Đổi tên: "Onmyoji Auto" → "Onmyoji Tool"

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

## Icon

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

## Thông báo

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

## Đóng cửa sổ app là dừng hết

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

---

[← Về trang chính](../README.md)

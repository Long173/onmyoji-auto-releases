# Ghi chú kỹ thuật

Những chỗ đã trả giá để tìm ra. Đọc trước khi "sửa lại cho gọn".

---

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

- Năm tác vụ đang chạy được: Phá Kết Giới, Ném đậu, Thám hiểm chương, Phụ bản
  ngự hồn, Event. Các chế độ khác chưa có.
- Chỉ chạy trên Windows (`pywin32`, PrintWindow, PostMessage).
- Wiki cần checkout `onmyoji_wiki` nằm cạnh thư mục dự án để có dữ liệu và ảnh
  offline; không có thì phải đồng bộ từ Supabase.
- Phím tắt F1/F2 cần quyền hook toàn cục; nếu đăng ký thất bại, app ghi log và
  phím chỉ hoạt động khi cửa sổ đang được chọn.

---

[← Về trang chính](../README.md)

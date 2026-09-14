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

## Dùng thế nào

```
1. Mở game, vào màn hình của tác vụ muốn chạy (ví dụ Phá Kết Giới).
2. Mở app -> bấm "Quét cửa sổ"; mỗi cửa sổ game hiện thành một dòng.
3. Chọn tác vụ ở cột trái, chỉnh cấu hình nếu cần.
4. Bấm "Bắt đầu tác vụ này".
```

Bot chạy nền — bạn vẫn dùng máy bình thường trong lúc nó chạy. `F1` tạm dừng
hoặc chạy tiếp tất cả, `F2` kết thúc tất cả.

## Chạy từ mã nguồn

Cần Python 3.10+ trên Windows.

```bash
pip install -r requirements.txt
python decompiled/source/app.py          # thêm -v để log từng cú click
```

Trong checkout còn hai lối chạy nhanh:

| File                     | Dùng khi                                                    |
| ------------------------ | ----------------------------------------------------------- |
| `Launch.vbs`             | Chạy bình thường — không hiện cửa sổ terminal                |
| `Launch (Show Log).bat`  | Khi có lỗi — hiện log trực tiếp, bật chế độ chi tiết (`-v`)  |

Log ghi vào `logs/onmyoji_auto.log`, tự xoay vòng ở 5 MB (giữ 3 file cũ).

Chạy test:

```bash
pip install pytest
python -m pytest tests -q
```

Không cần mở game và không cần mạng: `GameControl`, worker và scanner đều được
thay bằng stub, không click gì cả. Test dùng dữ liệu wiki thật sẽ tự bỏ qua nếu
không có checkout `onmyoji_wiki`.

## Tài liệu

Chi tiết nằm trong `docs/`, mỗi file một chủ đề:

| Tài liệu | Nội dung |
| --- | --- |
| [Kiến trúc](docs/kien-truc.md) | Cấu trúc thư mục, trách nhiệm từng module, cách Trung tâm tác vụ sinh ra từ registry, các quyết định về giao diện |
| [Các tác vụ auto](docs/tac-vu.md) | Từng vòng lặp hoạt động ra sao — Phá Kết Giới, Ngự hồn, Ném đậu, đếm vé, lời mời truy |
| [Bách khoa](docs/bach-khoa.md) | Nguồn dữ liệu wiki, đồng bộ Supabase, chỗ hai nguồn không khớp |
| [Đóng gói và phát hành](docs/dong-goi-va-phat-hanh.md) | Build .exe, phát hành lên GitHub Releases, cơ chế app tự thay chính nó |
| [Ghi chú kỹ thuật](docs/ghi-chu-ky-thuat.md) | Những chỗ đã trả giá để tìm ra — DPI, chụp màn hình, toạ độ. Đọc trước khi sửa |

Muốn thêm một tác vụ auto mới thì bắt đầu ở
[Kiến trúc → Thêm một tác vụ mới](docs/kien-truc.md#thêm-một-tác-vụ-mới):
khai một `TaskSpec` trong `decompiled/source/tasks.py` là xong, không đụng file
giao diện nào.

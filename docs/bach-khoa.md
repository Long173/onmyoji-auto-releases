# Bách khoa

Trang tra cứu Thức thần / Ngự hồn / Hiệu ứng: nguồn dữ liệu, đồng bộ Supabase,
và chỗ hai nguồn không khớp nhau.

---

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
2. `.env` cạnh app (hoặc ở gốc checkout)
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

## Muốn cập nhật dữ liệu wiki mà không build lại

Tạo thư mục `wiki\assets\data` (và `wiki\assets\images`) cạnh exe — app ưu tiên
dữ liệu ở đó hơn bản nhúng trong file.

---

[← Về trang chính](../README.md)

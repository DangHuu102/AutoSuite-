# Bộ tài liệu mẫu giả lập (`sample-documents/synthetic/`)

Bộ tài liệu này hoàn toàn là dữ liệu giả lập (không chứa thông tin nội bộ thật), dùng để kiểm thử nhanh luồng chuyển đổi Office sang PDF, OCR tiếng Việt và phân loại AI theo hướng dẫn tại [`specs/001-office-to-pdf-batch/quickstart.md`](../../specs/001-office-to-pdf-batch/quickstart.md):

- `Bao-cao-hanh-chinh-2026.docx`: Tài liệu Word tiếng Việt có dấu (kiểm thử chuyển `.docx` → PDF 1 trang và phân loại AI nhóm **Hành chính**).
- `Bang-ke-chi-phi-2026.xlsx`: Bảng tính Excel gồm 2 trang tính `Tong-hop` và `Chi-tiet` (kiểm thử phân trang nhiều sheet `.xlsx` → PDF 2 trang).
- `Trinh-chieu-ke-hoach-2026.pptx`: Bài trình chiếu PowerPoint có 2 slide, trong đó slide 2 được đặt ẩn `show="0"` (kiểm thử bộ lọc `ExportHiddenSlides=false` chỉ xuất 1 trang hiển thị).
- `Ho-so-scan-2-trang.pdf`: PDF scan giả lập 2 trang ảnh raster chưa có lớp chữ (kiểm thử OCR tiếng Việt tạo lớp chữ tìm kiếm được trên cả 2 trang).
- `Giay-de-nghi-thanh-toan.png`: Ảnh scan 300 DPI có chữ in tiếng Việt rõ nét (kiểm thử chuyển 1 ảnh → 1 PDF kèm lớp chữ OCR và phân loại AI nhóm **Tài chính**).

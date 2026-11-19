# Data Model: Chuyển Office và OCR PDF/ảnh scan theo lô

## Entities

### BatchJob

Một lần người dùng chọn, kiểm tra và chuyển đổi nhiều tệp.

| Field | Meaning |
| --- | --- |
| batch_id | Mã nội bộ duy nhất trong phiên |
| created_at | Thời điểm bắt đầu |
| destination | Thư mục đích đã chọn |
| state | selected, preflight, converting, review, committed, cancelled, failed |
| source_count | Số tệp được chọn |
| succeeded_count | Số PDF tạm đã tạo |
| failed_count | Số tệp lỗi |
| committed_count | Số PDF đã chuyển vào thư mục đích |

State transitions:

    selected -> preflight -> converting -> review -> committed
    selected/preflight/converting/review -> cancelled
    converting -> review (partial failures allowed)
    preflight -> failed (no processable files)

### SourceFile

Một tệp nguồn được chọn.

| Field | Meaning |
| --- | --- |
| source_id | Mã nội bộ duy nhất trong lô |
| original_name | Tên tệp gốc |
| extension | docx, xlsx, pptx, pdf, png, jpg, jpeg, tif, tiff, hoặc bmp |
| byte_size | Kích thước tệp |
| source_location | Vị trí cục bộ hoặc vùng nhận tệp trong phiên |
| status | selected, valid, converting, converted, failed, skipped |
| issues | Danh sách cảnh báo/lỗi liên quan |
| proposed_output_name | Tên PDF dự kiến, được phân biệt khi trùng |

Validation rules:

- Office phải thuộc .docx, .xlsx hoặc .pptx; scan nhận PDF và ảnh .png/.jpg/.jpeg/.tif/.tiff/.bmp.
- Tệp phải đọc được bởi bộ chuyển đổi/OCR; PDF mã hóa bị từ chối.
- Định dạng macro-enabled, Office cũ và TIFF nhiều khung bị từ chối trong MVP.
- Các lỗi đọc/chuyển đổi gắn với riêng tệp, không làm dừng lô.

### OutputPdf

PDF tạo từ một SourceFile.

| Field | Meaning |
| --- | --- |
| output_id | Mã nội bộ duy nhất |
| source_id | Tệp nguồn tạo ra PDF |
| proposed_name | Tên mặc định được đề xuất |
| final_name | Tên đã được người dùng duyệt |
| staging_path | Vị trí tạm trước khi commit |
| destination_path | Vị trí cuối sau khi xác nhận |
| page_count | Số trang nếu đọc được |
| searchable_text | Có thể trích văn bản OCR hay không; chỉ áp dụng cho PDF/ảnh scan |
| status | staged, previewed, committed, discarded, failed |

Invariants:

- Mỗi tệp nguồn hợp lệ có tối đa một PDF đầu ra.
- Không thay đổi hoặc xóa tệp nguồn.
- Không ghi đè tệp trong thư mục đích khi chưa có xác nhận.
- PDF tạm chỉ được đưa sang thư mục đích sau thao tác xác nhận.
- PDF tạm bị xóa nếu lô bị hủy hoặc kết thúc lưu.

### ConversionIssue

Một lỗi hoặc cảnh báo gắn với tệp nguồn hay PDF đầu ra.

| Field | Meaning |
| --- | --- |
| issue_code | unsupported_type, unreadable, password_protected, conversion_failed, ocr_failed, name_conflict, destination_error, preview_warning |
| severity | warning hoặc error |
| message_vi | Thông báo dễ hiểu bằng tiếng Việt |
| source_id | Tệp liên quan |
| blocks_commit | Có chặn lưu hay không |

### OCR settings

- Ngôn ngữ: `vie` mặc định; tùy chọn `eng` hoặc `vie+eng`.
- OCR chạy cục bộ bằng OCRmyPDF/Tesseract và gói traineddata đã cài.
- PDF scan giữ ảnh/trang gốc; ảnh đơn tạo một PDF riêng; nhiều ảnh không ghép thành cùng một PDF.
- Tối đa 20 tệp và tổng dung lượng 500 MB cho mỗi lô.

### AIFilterSuggestion

Gợi ý tạm thời do model cục bộ tạo khi người dùng chủ động yêu cầu.

| Field | Meaning |
| --- | --- |
| output_id | PDF tạm được phân loại |
| decision | keep, skip, hoặc review; chỉ là gợi ý |
| category | Nhóm tài liệu gợi ý |
| suggested_basename | Tên PDF gợi ý, người dùng có thể sửa |
| reason | Lý do ngắn do model trả về |

Invariants:

- Chỉ trích tối đa 8 trang đầu và 12.000 ký tự từ PDF; không gửi tệp nguồn.
- Chỉ gọi runtime/model đã cài cục bộ qua loopback; không theo HTTP redirect hoặc proxy.
- AI không tự đổi ô chọn, xóa, commit hoặc ghi tên cuối cùng.
- Gợi ý bị xóa khi phiên xử lý kết thúc; không lưu văn bản trích hoặc nội dung tài liệu trong log.

## Data lifecycle

1. Tệp được chọn và kiểm tra trong phiên cục bộ.
2. Bản xử lý tạm được chuyển đổi vào thư mục staging.
3. Người dùng xem PDF, sửa tên hoặc bỏ tệp lỗi.
4. Nếu người dùng chủ động gọi AI, một đoạn trích có giới hạn được gửi tới model cục bộ và gợi ý chỉ ở trong phiên; người dùng xem lại trước khi có thể áp dụng.
5. Khi xác nhận, PDF được chuyển vào thư mục đích và trạng thái lô cập nhật.
6. Khi hủy hoặc hoàn tất, dữ liệu tạm được xóa; không giữ lịch sử có nội dung tài liệu.

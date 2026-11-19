# Quickstart: Chuyển Office và OCR PDF/ảnh scan

Hướng dẫn chạy prototype và xác nhận bằng tay; kết quả OCR cần được người dùng xem lại trước khi lưu.

## Prerequisites

- Windows 11.
- Python 3.12 và các gói ứng dụng đã cài trong môi trường ảo.
- LibreOffice đã cài để xử lý .docx, .xlsx, .pptx.
- OCRmyPDF, Tesseract và gói ngôn ngữ OCR đã cài cục bộ để xử lý PDF/ảnh scan. Tối thiểu cần `vie.traineddata`; `eng.traineddata` cần cho tiếng Anh hoặc `vie+eng`.
- Bộ mẫu giả lập: một file .docx tiếng Việt, .xlsx nhiều trang tính, .pptx có slide ẩn, PDF scan nhiều trang và ảnh có chữ in rõ.
- Không dùng hồ sơ hoặc tài liệu nội bộ thật trong bước đầu.
- (Tùy chọn) Ollama và một model local nếu cần gợi ý lọc AI. Chuyển đổi/OCR không phụ thuộc AI.

## Start the local app

Từ thư mục gốc dự án:

    uv venv --python 3.12
    .\.venv\Scripts\Activate.ps1
    uv pip install -e .
    python -m streamlit run src/officeflow/app.py

Giao diện dự kiến mở tại địa chỉ localhost hiển thị trong terminal. Kiểm tra cấu hình không cho phép thiết bị khác trong mạng truy cập và không gửi telemetry.

## Manual validation flow

1. Chọn một .docx, một .xlsx, một .pptx, một PDF scan và một ảnh cùng lúc.
2. Kiểm tra danh sách đầu vào, tên PDF dự kiến, định dạng và cảnh báo.
3. Bắt đầu chuyển đổi; xác nhận tiến độ và trạng thái hiện riêng cho từng tệp.
4. Mở PDF tạm; xem tiếng Việt, phân trang Excel, số trang, slide PowerPoint, ảnh nguồn và lớp chữ OCR. Thử tìm kiếm/chọn chữ trong PDF scan.
5. Xác nhận lưu vào một thư mục trống; kiểm tra có đúng một PDF cho mỗi nguồn hợp lệ và tệp nguồn không đổi.
6. Lặp lại với hai tệp cùng tên từ hai thư mục; xác nhận tên PDF có hậu tố và không bị ghi đè.
7. Thử tệp sai phần mở rộng, Office/PDF hỏng, PDF khóa mật khẩu hoặc thiếu gói `vie`; xác nhận lỗi được báo theo tệp và tệp hợp lệ còn lại vẫn chuyển đổi.
8. Hủy lô trước bước xác nhận; xác nhận thư mục đích không có PDF mới và dữ liệu staging được dọn.
9. (Tùy chọn) Chạy Ollama cục bộ, tải một model hỗ trợ tiếng Việt (ví dụ `ollama pull qwen3.5:4b`), mở phần gợi ý AI, kiểm tra model hiện có và phân loại PDF theo một yêu cầu cụ thể.
10. Kiểm tra AI chỉ đề xuất; thử áp dụng lựa chọn, chỉnh lại ít nhất một PDF, xác nhận bỏ chọn không xóa dữ liệu tạm và bước xác nhận lưu vẫn bắt buộc.

## Expected outcomes

- Một nguồn hợp lệ tương ứng với một PDF mở được.
- Không tệp nguồn nào bị thay đổi.
- Tên trùng không bị ghi đè âm thầm.
- Tệp lỗi được báo riêng; lỗi không làm dừng toàn bộ lô.
- PDF scan giữ nội dung trang; ảnh scan thành một PDF riêng và có lớp chữ OCR khi gói ngôn ngữ cài đúng.
- OCR có thể nhận sai chữ mờ, chữ viết tay hoặc scan lệch; luôn xem lại nội dung trước khi lưu.
- PDF chỉ vào thư mục đích sau khi người dùng xác nhận.
- AI chỉ đọc một đoạn trích PDF đã giới hạn qua Ollama loopback; nếu model không sẵn có, tính năng AI báo lỗi mà không chặn chuyển đổi.

## Kiểm tra nhanh trên máy hiện tại (2026-11-19)

- Python 3.12.16 và dependencies của project đã được cài trong `.venv`.
- Lệnh `python -m compileall -q src/officeflow` chạy thành công.
- Health endpoint của Streamlit trả HTTP 200; app được phục vụ trên `127.0.0.1:8501`.
- Chưa tìm thấy LibreOffice, Tesseract hoặc Ollama. OCRmyPDF đã có trong môi trường Python, nhưng OCR chưa chạy được khi thiếu Tesseract và dữ liệu ngôn ngữ.
- Chưa xác nhận chuyển đổi tài liệu, chất lượng đầu ra OCR hoặc phản hồi của model AI thật. Cần cài các phần phụ thuộc hệ thống và một model Ollama cục bộ rồi chạy luồng chấp nhận ở trên.


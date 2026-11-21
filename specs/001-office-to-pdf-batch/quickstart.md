# Quickstart: Chuyển Office và OCR PDF/ảnh scan

Hướng dẫn chạy prototype và xác nhận bằng tay; kết quả OCR cần được người dùng xem lại trước khi lưu.

## Prerequisites

- Windows 11.
- Python 3.12 và các gói ứng dụng đã cài trong môi trường ảo.
- LibreOffice đã cài để xử lý .docx, .xlsx, .pptx. Đây là bộ máy xuất PDF của prototype; Microsoft Office đã cài không được app tự gọi. Cài song song bằng `winget install -e --id TheDocumentFoundation.LibreOffice` nếu chưa có.
- OCRmyPDF, Tesseract và gói ngôn ngữ OCR đã cài cục bộ để xử lý PDF/ảnh scan. Tối thiểu cần `vie.traineddata`; `eng.traineddata` cần cho tiếng Anh hoặc `vie+eng`. LibreOffice không cần nếu lô chỉ có PDF/ảnh.
- Bộ mẫu giả lập: một file .docx tiếng Việt, .xlsx nhiều trang tính, .pptx có slide ẩn, PDF scan nhiều trang và ảnh có chữ in rõ.
- Không dùng hồ sơ hoặc tài liệu nội bộ thật trong bước đầu.
- (Tùy chọn) Ollama và một model local nếu cần AI riêng tư; hoặc API key OpenAI nếu muốn dùng cloud. Chuyển đổi/OCR không phụ thuộc AI.

## Start the local app

Từ thư mục gốc dự án:

    uv venv --python 3.12
    .\.venv\Scripts\Activate.ps1
    uv pip install -e ".[desktop]"
    officeflow-desktop

Ứng dụng mở trong cửa sổ Windows riêng. Nó chạy giao diện Streamlit trên `127.0.0.1` và tự tắt tiến trình khi đóng cửa sổ. WebView2 Runtime phải có trên máy.

Để mở giao diện web trực tiếp, thay dòng cuối bằng `python -m streamlit run src/officeflow/app.py`.

## CLI

Chuyển một nhóm tệp đã chọn rõ ràng:

    officeflow convert .\Bao-cao.docx .\Scan.pdf --output-dir .\PDF --ocr-language vie

Liệt kê model Ollama và gợi ý cho một PDF đã có lớp chữ:

    officeflow ai models
    officeflow ai classify .\PDF\Bao-cao.pdf --provider ollama --model qwen3.5:4b --filter "Giữ tài liệu hành chính năm 2026"

CLI báo lỗi theo từng tệp, chọn tên không ghi đè âm thầm và trả mã thoát khác 0 nếu có lỗi. Lệnh chuyển đổi CLI ghi PDF ngay vào thư mục đích theo yêu cầu của lệnh; dùng giao diện nếu cần xem trước trước khi lưu.

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
10. (Tùy chọn) Cấu hình `OPENAI_API_KEY`, chọn OpenAI API và xác nhận chia sẻ đoạn trích; kiểm tra chỉ nội dung giới hạn được gửi và kết quả AI vẫn cần người dùng duyệt.
11. Kiểm tra AI chỉ đề xuất; thử áp dụng lựa chọn, chỉnh lại ít nhất một PDF, xác nhận bỏ chọn không xóa dữ liệu tạm và bước xác nhận lưu vẫn bắt buộc.
12. Dùng CLI chuyển nhóm tài liệu giả lập; lặp lại với tên PDF đã tồn tại và xác nhận không có tệp bị ghi đè.

## Expected outcomes

- Một nguồn hợp lệ tương ứng với một PDF mở được.
- Không tệp nguồn nào bị thay đổi.
- Tên trùng không bị ghi đè âm thầm.
- Tệp lỗi được báo riêng; lỗi không làm dừng toàn bộ lô.
- PDF scan giữ nội dung trang; ảnh scan thành một PDF riêng và có lớp chữ OCR khi gói ngôn ngữ cài đúng.
- OCR có thể nhận sai chữ mờ, chữ viết tay hoặc scan lệch; luôn xem lại nội dung trước khi lưu.
- PDF chỉ vào thư mục đích sau khi người dùng xác nhận.
- Ollama chỉ nhận đoạn trích PDF đã giới hạn qua loopback. OpenAI API chỉ nhận đoạn trích sau khi người dùng đồng ý. Thiếu AI/API key không chặn chuyển đổi/OCR.

## Kiểm tra nhanh trên máy hiện tại (2026-11-22)

- Python 3.12.16 và dependencies của project (bao gồm extra `desktop` với `pywebview`) đã được cài trong `.venv`.
- Lệnh `python -m compileall -q src/officeflow` chạy thành công.
- Health endpoint của Streamlit (`/_stcore/health`) trả HTTP 200 trên cổng loopback ngẫu nhiên `127.0.0.1` và tự đóng sạch tiến trình khi kết thúc.
- Bộ tài liệu mẫu giả lập đã được tạo sẵn tại `sample-documents/synthetic/`:
  - `Bao-cao-hanh-chinh-2026.docx` (Word tiếng Việt 1 trang)
  - `Bang-ke-chi-phi-2026.xlsx` (Excel 2 trang tính `Tong-hop` và `Chi-tiet`)
  - `Trinh-chieu-ke-hoach-2026.pptx` (PowerPoint 2 slide, trong đó slide 2 ẩn `show="0"`)
  - `Ho-so-scan-2-trang.pdf` (PDF scan 2 trang ảnh raster tiếng Việt)
  - `Giay-de-nghi-thanh-toan.png` (Ảnh scan `.png` 300 DPI chữ tiếng Việt)
- Các runtime cục bộ đã có trên máy:
  - LibreOffice Desktop: `C:\Program Files\LibreOffice\program\soffice.exe`.
  - OCRmyPDF: `.venv\Scripts\ocrmypdf.exe` (17.13.0) và Tesseract: `C:\Program Files\Tesseract-OCR\tesseract.exe` (5.4.0.20240606).
  - Gói dữ liệu ngôn ngữ OCR (`vie.traineddata`, `eng.traineddata`, `osd.traineddata` cùng `configs/`, `tessconfigs/`, `pdf.ttf`) đã được cấu hình tại `.tesseract/tessdata` và được `officeflow.ocr` tự động nạp qua `TESSDATA_PREFIX`.
  - Ollama CLI/Service (`0.40.16`) đã cài tại `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` cùng model cục bộ `qwen3.5:4b` trong `.ollama-models`.
- Kết quả xác nhận luồng chuyển đổi, OCR, CLI và Ollama thực tế (T030 & T037):
  - Lô hỗn hợp 5 tệp trong `sample-documents/synthetic/` đã chuyển đổi thành công sang 5 tệp PDF mở được; `.xlsx` giữ đủ 2 trang, `.pptx` loại bỏ slide ẩn (còn 1 trang), PDF scan 2 trang và ảnh `.png` đều tạo lớp chữ OCR tiếng Việt chính xác (`searchable_text = True`), và SHA-256 của tệp nguồn không thay đổi.
  - Trùng tên trong cùng lô và với thư mục đích tự động sinh hậu tố `(1)`, `(2)` không ghi đè; hủy lô xóa sạch thư mục staging và giữ nguyên thư mục đích.
  - Lô có tệp lỗi (`.docx` hỏng, `.docm` macro-enabled, `.pdf` đặt mật khẩu, `.tiff` nhiều khung) báo đúng mã lỗi theo từng tệp, vẫn chuyển đổi tệp hợp lệ còn lại và tạo được lô thử lại (`create_retry_batch`) cho tệp lỗi.
  - CLI `officeflow convert` chạy thành công với `--ocr-language vie` và `vie+eng`, tự đổi tên tránh ghi đè khi chạy lặp lại trên cùng thư mục đích, và trả mã thoát `1` khi trong lô có tệp lỗi.
  - CLI `officeflow ai models` liệt kê đúng `qwen3.5:4b`. Với cấu hình `"think": False` và `"num_predict": 300` trong `src/officeflow/ai_filter.py`, lệnh `officeflow ai classify --provider ollama --model qwen3.5:4b` phân loại trực tiếp chính xác cả PDF từ Word (`Bao-cao-hanh-chinh-2026.pdf` → `decision: "keep"`, `category: "Hành chính"`) và PDF từ ảnh OCR (`Giay-de-nghi-thanh-toan.pdf` → `decision: "skip"`, `category: "Tài chính"`).
  - CLI `officeflow ai classify` chặn gọi OpenAI khi thiếu `--allow-cloud` hoặc thiếu `OPENAI_API_KEY`.
  - CLI `officeflow doctor` và `officeflow doctor --json` kiểm tra tức thì trạng thái LibreOffice, OCRmyPDF, Tesseract, `tessdata` (`vie`, `eng`, `osd`), staging, `pywebview`, Ollama và OpenAI (ẩn hoàn toàn giá trị khóa bí mật).
  - Tính năng tùy chọn ghép nhiều ảnh scan thành 1 PDF nhiều trang có OCR (`--merge-images NAME.pdf` trên CLI và ô chọn trong giao diện) tạo PDF nhiều trang tìm kiếm được, kèm cơ chế cô lập lỗi từng ảnh nếu 1 ảnh trong nhóm bị hỏng.
  - Bộ kiểm thử tự động `tests/` (27 test cases: unit test cho `naming`, `validation`, `staging`, `batch`, `reporting`, `ai_filter`, `cli`, `doctor`, `merge_images` và integration test với LibreOffice + OCRmyPDF/Tesseract) chạy `python -m unittest discover -s tests -v` đạt **27/27 OK**.


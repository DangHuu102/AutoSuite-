# OfficeFlow

Ứng dụng cục bộ để chuyển nhiều tài liệu Word, Excel, PowerPoint sang PDF; nhận thêm PDF scan và ảnh để tạo PDF có lớp chữ OCR. Mỗi nguồn hợp lệ tạo một PDF riêng. Bạn có thể xem lại và chỉnh tên trước khi lưu.

## Yêu cầu

- Windows 11 64-bit.
- Python 3.12.
- LibreOffice Desktop để chuyển `.docx`, `.xlsx`, `.pptx`. Đây là bộ máy dàn trang/xuất PDF cục bộ của prototype, không phải gói Python và không thay Microsoft Office.
- OCRmyPDF và Tesseract cho PDF/ảnh scan. Cài gói ngôn ngữ Tesseract tương ứng: `vie` mặc định, `eng` cho tiếng Anh, hoặc cả hai cho `vie+eng`.

Python điều phối giao diện và các bước xử lý; tự nó không dàn trang tài liệu Office thành PDF. Bản hiện tại gọi LibreOffice ở chế độ dòng lệnh vì xử lý được cả Word, Excel và PowerPoint tại máy, không tải tài liệu lên dịch vụ ngoài. Việc Microsoft Office có sẵn trên máy không làm ứng dụng tự dùng Word/Excel/PowerPoint. Nếu chỉ OCR PDF/ảnh scan thì không cần LibreOffice.

Ứng dụng chỉ lắng nghe tại `127.0.0.1`, xử lý tệp trên máy hiện tại và tắt usage statistics. Tệp được đưa vào thư mục tạm cục bộ khi xử lý; thư mục staging được dọn sau khi lưu/hủy và các lô bỏ dở được dọn sau 48 giờ.

## Cài đặt trên Windows

Mở PowerShell tại thư mục dự án. Cách khuyến nghị nếu đã có `uv`:

```powershell
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install -e .
```

Nếu đã cài Python 3.12 và Python Launcher, có thể dùng `py -3.12 -m venv .venv`, kích hoạt môi trường trên rồi chạy `python -m pip install -e .`.

Cài LibreOffice Desktop nếu cần chuyển tài liệu Office. Có thể tải từ [trang chính thức của LibreOffice](https://www.libreoffice.org/download/) hoặc dùng Windows Package Manager:

```powershell
winget install -e --id TheDocumentFoundation.LibreOffice
```

LibreOffice cài song song với Microsoft Office. Sau khi cài, khởi động lại OfficeFlow để ứng dụng dò `soffice.exe`.

Chỉ cài Tesseract 64-bit nếu cần OCR. OCRmyPDF được cài cùng gói Python của project; nếu Tesseract chưa có trong `PATH`, OCRmyPDF cũng dò các vị trí cài đặt Windows thông dụng. Trang cài đặt OCRmyPDF có hướng dẫn Windows hiện hành: [OCRmyPDF installation](https://ocrmypdf.readthedocs.io/en/stable/installation.html).

Nếu máy có Windows Package Manager, có thể cài Tesseract bằng:

```powershell
winget install -e --id tesseract-ocr.tesseract
```

Đảm bảo gói `vie.traineddata` có trong thư mục `tessdata` của Tesseract. Cần cài thêm `eng.traineddata` nếu chọn tiếng Anh hoặc kết hợp. Chạy `tesseract --list-langs` trong PowerShell để xem các ngôn ngữ đã nhận diện qua PATH.

Các gói ngôn ngữ chính thức nằm trong [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) hoặc [tessdata_best](https://github.com/tesseract-ocr/tessdata_best); chép tệp `.traineddata` cần dùng vào thư mục `tessdata` của Tesseract.

## Chạy ứng dụng

```powershell
python -m streamlit run src/officeflow/app.py
```

Mở địa chỉ localhost mà Streamlit hiển thị. Chọn tối đa 20 tệp, chọn thư mục lưu, kiểm tra tên, tạo PDF xem trước, xác nhận những PDF cần lưu.

## Định dạng

- Office: `.docx`, `.xlsx`, `.pptx`.
- OCR scan: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`.
- Một ảnh tạo một PDF; MVP chưa ghép nhiều ảnh thành một PDF nhiều trang.
- Không nhận định dạng Office cũ, macro-enabled, GIF, HEIC hoặc TIFF nhiều khung.
- Mỗi tệp tối đa 100 MB qua giao diện; tối đa 20 tệp mỗi lô.
- Tổng dung lượng mỗi lô tối đa 500 MB để giới hạn bộ nhớ tạm.

## Gợi ý lọc bằng AI cục bộ (tùy chọn)

AI không bắt buộc để chuyển đổi hoặc OCR. Nếu cần phân loại PDF theo nội dung, cài [Ollama](https://ollama.com/download), tải một model có khả năng đọc tiếng Việt (ví dụ `qwen3.5:4b`) rồi mở Ollama trước khi chạy ứng dụng:

```powershell
ollama pull qwen3.5:4b
```

Trong bước xem lại, mở **Gợi ý lọc và đặt tên bằng AI cục bộ**, kiểm tra model Ollama đang có, nhập yêu cầu lọc và chạy phân loại. Hệ thống chỉ gửi tối đa 8 trang đầu và 12.000 ký tự trích từ PDF tạm tới Ollama qua `127.0.0.1`; không gọi API cloud. Chỉ model được cài cục bộ mới xuất hiện trong danh sách.

Để thay đổi giới hạn chờ (mặc định 45 giây, cho phép 5–180 giây), đặt biến môi trường trước khi khởi chạy, ví dụ `$env:OFFICEFLOW_AI_TIMEOUT_SECONDS = "90"` trong PowerShell. App phân loại từng tệp một để không giữ giao diện bận trong suốt cả lô.

AI gợi ý nhóm, giữ/bỏ qua/xem lại, lý do và tên PDF. Gợi ý không tự xóa, bỏ chọn hoặc lưu tệp. Nếu chọn áp dụng gợi ý, hãy kiểm tra lại từng tệp và xác nhận lưu như bình thường. Tài liệu scan cần có lớp chữ OCR để AI đọc được.

## Giới hạn cần biết

- LibreOffice có thể dàn trang khác Microsoft Office do phông chữ, phiên bản hoặc thiết lập in. Luôn kiểm tra PDF trước khi lưu.
- OCR không đảm bảo chính xác với scan mờ, nghiêng, độ phân giải thấp hoặc chữ viết tay. Nội dung OCR chỉ để tìm kiếm/chọn/sao chép, không phải tài liệu Office đã chỉnh sửa.
- OCR PDF sẽ bỏ qua trang đã có chữ để không xử lý lại lớp chữ sẵn có. Tệp nguồn không bị thay đổi.
- Không OCR PDF đã ký số nếu cần giữ hiệu lực chữ ký. Hãy dùng bản chưa ký rồi kiểm tra lại sau OCR.
- Nếu thiếu LibreOffice khi lô có DOCX/XLSX/PPTX, hoặc thiếu OCRmyPDF/Tesseract/gói ngôn ngữ khi lô có PDF/ảnh scan, giao diện sẽ báo theo loại tệp.

Hướng dẫn thao tác và xác nhận bằng tay nằm trong [quickstart](specs/001-office-to-pdf-batch/quickstart.md).

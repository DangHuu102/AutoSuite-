# AutoSuite (OfficeFlow v0.3.0)

Ứng dụng web & desktop siêu nhẹ RAM (`~32.8 MB` khi chờ) giúp **chuyển đổi PDF sang Word (`.docx`) giữ nguyên bảng biểu**, chuyển tài liệu **Word, Excel, PowerPoint sang PDF**, nhận diện chữ **OCR tiếng Việt/tiếng Anh** cho PDF scan & ảnh chụp, ghép nhiều ảnh thành 1 PDF, và phân loại thông minh bằng AI (Ollama cục bộ hoặc OpenAI API tùy chọn).

## Điểm nổi bật (v0.3.0)

- **Tự điều hướng thông minh (0ms Smart Auto-Routing)**: Kéo thả bất kỳ tệp `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.png`, `.jpg`, `.tif`, `.bmp` hoặc nhấn `Ctrl+V` dán ảnh chụp màn hình — web tự động nhận diện công cụ phù hợp nhất và tự chuyển mượt qua 3 bước (`#upload` → `#converting` → `#download`) có hỗ trợ nút Quay lại (Back/Forward) của trình duyệt.
- **Siêu nhẹ RAM & Tốc độ tức thì**: Chạy trên nền **Starlette + Uvicorn** kết hợp giao diện **Vanilla HTML5/CSS/JS SPA không phụ thuộc ngoài**, giảm ~85% lượng RAM tiêu thụ so với Streamlit cũ (`~32.8 MB` RAM khi chờ thay vì `~220+ MB`), truyền tải tệp theo từng khối `64 KB` trực tiếp ra đĩa tạm mà không nạp toàn bộ tệp vào RAM.
- **Tải xuống chuẩn Web Tải Video / MP4 / iLovePDF**:
  - **Nút chính `⬇ Tải xuống máy`**: Luồng HTTP `Content-Disposition: attachment` chuẩn RFC 5987 (hỗ trợ đầy đủ tên tiếng Việt có dấu) kích hoạt thanh Download gốc của trình duyệt ngay lập tức với `0 MB` RAM JS, không bao giờ quét hay truy vấn thư mục máy chủ `C:\Users\...`.
  - **Nút phụ `📁 Chọn vị trí lưu (Save As…)`**: Dùng `showSaveFilePicker` / `showDirectoryPicker` kết hợp `ReadableStream.pipeTo()` ghi thẳng xuống ổ đĩa bất kỳ (`D:\`, `E:\`, Desktop…) không cần mã hóa Base64.

## Yêu cầu hệ thống

- Windows 10/11 64-bit hoặc Linux Server (Docker / VPS).
- Python 3.12.
- **LibreOffice Desktop** để xuất `.docx`, `.xlsx`, `.pptx` sang PDF (`winget install -e --id TheDocumentFoundation.LibreOffice`).
- **OCRmyPDF + Tesseract OCR** kèm gói ngôn ngữ `vie`, `eng`, `osd` cho ảnh chụp và PDF scan (`winget install -e --id tesseract-ocr.tesseract`).

## Cài đặt & Khởi chạy trên Windows

```powershell
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[desktop]"
```

### 1. Chạy Web cục bộ siêu nhanh (`http://autosuite.localhost:8501`)

Nhấp đúp `Chay-AutoSuite.bat` hoặc chạy lệnh:

```powershell
python -m uvicorn officeflow.webapp:app --app-dir src --host 127.0.0.1 --port 8501
```

### 2. Chạy ngầm 24/24 tự khởi động cùng Windows

Nhấp đúp `Cai-dat-tu-chay-khi-bat-may.bat` hoặc chạy:

```powershell
python -m officeflow.daemon_24x7
```

### 3. Mở cửa sổ ứng dụng Desktop riêng (WebView2)

```powershell
officeflow-desktop
```

### 4. Triển khai lên VPS / Cloud Server 24/24 (Docker)

```bash
docker compose up -d --build
```

## Dùng qua Dòng lệnh (CLI)

```powershell
# Kiểm tra môi trường cục bộ
officeflow doctor

# Chuyển PDF sang Word (.docx) giữ nguyên bảng biểu
officeflow convert .\Bang-ke-chi-phi-2026.pdf --output-dir .\Out --to docx

# Chuyển Office & Ảnh Scan sang PDF có OCR + Xuất báo cáo CSV/JSON
officeflow convert .\Bao-cao.docx .\Scan.png --output-dir .\PDF --ocr-language vie --report-csv .\PDF\report.csv

# Ghép nhiều ảnh chụp thành 1 tệp PDF nhiều trang
officeflow convert .\Trang-1.png .\Trang-2.png --output-dir .\PDF --merge-images Ho-so-ghep.pdf

# Phân loại PDF bằng AI cục bộ (Ollama)
officeflow ai models
officeflow ai classify .\PDF\Bao-cao.pdf --provider ollama --model qwen3.5:4b --filter "Giữ tài liệu hành chính"
```

## Kiểm thử tự động

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```

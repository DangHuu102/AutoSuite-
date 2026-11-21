# OfficeFlow

Ứng dụng Windows để chuyển nhiều tài liệu Word, Excel, PowerPoint sang PDF; nhận thêm PDF scan và ảnh để tạo PDF có lớp chữ OCR. Có giao diện desktop, giao diện web cục bộ và CLI. AI có thể chạy trên Ollama hoặc gọi OpenAI API theo lựa chọn của bạn.

## Yêu cầu

- Windows 11 64-bit.
- Python 3.12.
- LibreOffice Desktop để chuyển `.docx`, `.xlsx`, `.pptx`. Đây là bộ máy dàn trang/xuất PDF cục bộ của prototype, không phải gói Python và không thay Microsoft Office.
- OCRmyPDF và Tesseract cho PDF/ảnh scan. Cài gói ngôn ngữ Tesseract tương ứng: `vie` mặc định, `eng` cho tiếng Anh, hoặc cả hai cho `vie+eng`.

Python điều phối giao diện và các bước xử lý; tự nó không dàn trang tài liệu Office thành PDF. Bản hiện tại gọi LibreOffice ở chế độ dòng lệnh vì xử lý được cả Word, Excel và PowerPoint tại máy. Chuyển đổi và OCR chạy cục bộ; chỉ tùy chọn OpenAI mới gửi phần văn bản trích xuất lên API sau khi bạn đồng ý. Việc Microsoft Office có sẵn trên máy không làm ứng dụng tự dùng Word/Excel/PowerPoint. Nếu chỉ OCR PDF/ảnh scan thì không cần LibreOffice.

Ứng dụng chỉ lắng nghe tại `127.0.0.1`, xử lý tệp trên máy hiện tại và tắt usage statistics. Tệp được đưa vào thư mục tạm cục bộ khi xử lý; thư mục staging được dọn sau khi lưu/hủy và các lô bỏ dở được dọn sau 48 giờ.

## Cài đặt trên Windows

Mở PowerShell tại thư mục dự án. Cách khuyến nghị nếu đã có `uv`:

```powershell
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[desktop]"
```

Nếu đã cài Python 3.12 và Python Launcher, có thể dùng `py -3.12 -m venv .venv`, kích hoạt môi trường trên rồi chạy `python -m pip install -e ".[desktop]"`.

Giao diện desktop mở trong cửa sổ riêng của Windows, khởi chạy dịch vụ Streamlit chỉ lắng nghe trên `127.0.0.1` và tự tắt dịch vụ khi đóng cửa sổ. Cần Microsoft Edge WebView2 Runtime (thường đã có trên Windows 11). Nếu chỉ cần web cục bộ hoặc CLI, có thể cài `uv pip install -e .` thay cho extra desktop.

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

Mở cửa sổ desktop:

```powershell
officeflow-desktop
```

Mở giao diện web cục bộ thủ công:

```powershell
python -m streamlit run src/officeflow/app.py
```

Mở địa chỉ localhost mà Streamlit hiển thị. Chọn tối đa 20 tệp, chọn thư mục lưu, kiểm tra tên, tạo PDF xem trước, xác nhận những PDF cần lưu.

## Dùng CLI

Kiểm tra nhanh môi trường và các công cụ cục bộ (`LibreOffice`, `OCRmyPDF`, `Tesseract`, `tessdata`, `pywebview`, `Ollama`):

```powershell
officeflow doctor
officeflow doctor --json
```

Chuyển một nhóm tệp trực tiếp sang thư mục PDF, ghép nhiều ảnh scan thành một PDF nhiều trang (`--merge-images`), kiểm tra trước (`--dry-run`) hoặc xuất báo cáo đối chiếu (`.json` / `.csv` chuẩn UTF-8 BOM cho Excel). CLI vẫn tránh ghi đè âm thầm và báo riêng tệp lỗi:

```powershell
officeflow convert .\Bao-cao.docx .\Bang-ke.xlsx .\Scan.pdf --output-dir .\PDF --ocr-language vie --report-csv .\PDF\bao-cao.csv --report-json .\PDF\bao-cao.json
officeflow convert .\Trang-1.png .\Trang-2.png --output-dir .\PDF --ocr-language vie --merge-images Ho-so-ghep.pdf
officeflow convert .\Bao-cao.docx .\Scan.pdf --output-dir .\PDF --dry-run
```

Xem các model Ollama cục bộ hoặc phân loại một hay nhiều PDF đã có lớp chữ:

```powershell
officeflow ai models
officeflow ai classify .\PDF\Bao-cao.pdf --provider ollama --model qwen3.5:4b --filter "Giữ tài liệu hành chính năm 2026"
officeflow ai classify .\PDF\Bao-cao.pdf .\PDF\Scan.pdf --provider ollama --model qwen3.5:4b --filter "Giữ tài liệu hành chính năm 2026"
```

## Dùng OpenAI API (tùy chọn)

OpenAI API là lựa chọn cloud riêng; không cần bật để chuyển đổi hoặc OCR. Tạo API key trong tài khoản API của bạn và nhập khóa an toàn vào phiên PowerShell trước khi mở desktop app hoặc gọi CLI:

```powershell
$secureKey = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
officeflow-desktop
```

Trong phần AI của giao diện, chọn **OpenAI API qua Internet**, đánh dấu đồng ý gửi đoạn trích và chọn model. Gọi trực tiếp bằng CLI cần cờ xác nhận rõ ràng:

```powershell
officeflow ai classify .\PDF\Bao-cao.pdf --provider openai --model gpt-6-luna --filter "Giữ tài liệu hành chính năm 2026" --allow-cloud
```

OfficeFlow trích tối đa 8 trang đầu và 12.000 ký tự; API nhận phần văn bản này chứ không nhận tệp PDF. Lời gọi dùng Responses API với đầu ra JSON theo schema và yêu cầu `store=false`. Dù vậy, nội dung vẫn được gửi qua Internet và API có thể tính phí. Không gửi hồ sơ nhạy cảm nếu bạn chưa được phép. OfficeFlow không ghi API key vào cấu hình dự án; xóa khóa khỏi phiên PowerShell sau khi dùng bằng `Remove-Item Env:OPENAI_API_KEY`.

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

Trong bước xem lại, chọn **Ollama chạy trên máy**, kiểm tra model Ollama đang có, nhập yêu cầu lọc và chạy phân loại. Tối đa 8 trang đầu và 12.000 ký tự trích từ PDF tạm được gửi tới Ollama qua `127.0.0.1`; dữ liệu không rời máy.

Để thay đổi giới hạn chờ (mặc định 45 giây, cho phép 5–180 giây), đặt biến môi trường trước khi khởi chạy, ví dụ `$env:OFFICEFLOW_AI_TIMEOUT_SECONDS = "90"` trong PowerShell. App phân loại từng tệp một để không giữ giao diện bận trong suốt cả lô.

AI gợi ý nhóm, giữ/bỏ qua/xem lại, lý do và tên PDF. Gợi ý không tự xóa hoặc lưu tệp. Nếu chọn áp dụng gợi ý trong giao diện, hãy kiểm tra lại từng tệp và xác nhận lưu như bình thường. Tài liệu scan cần có lớp chữ OCR để AI đọc được. CLI trả kết quả JSON và không tự đổi tên hay xóa tệp.

## Giới hạn cần biết

- LibreOffice có thể dàn trang khác Microsoft Office do phông chữ, phiên bản hoặc thiết lập in. Luôn kiểm tra PDF trước khi lưu.
- OCR không đảm bảo chính xác với scan mờ, nghiêng, độ phân giải thấp hoặc chữ viết tay. Nội dung OCR chỉ để tìm kiếm/chọn/sao chép, không phải tài liệu Office đã chỉnh sửa.
- OCR PDF sẽ bỏ qua trang đã có chữ để không xử lý lại lớp chữ sẵn có. Tệp nguồn không bị thay đổi.
- Không OCR PDF đã ký số nếu cần giữ hiệu lực chữ ký. Hãy dùng bản chưa ký rồi kiểm tra lại sau OCR.
- Nếu thiếu LibreOffice khi lô có DOCX/XLSX/PPTX, hoặc thiếu OCRmyPDF/Tesseract/gói ngôn ngữ khi lô có PDF/ảnh scan, giao diện sẽ báo theo loại tệp.

Hướng dẫn thao tác và xác nhận bằng tay nằm trong [quickstart](specs/001-office-to-pdf-batch/quickstart.md). Bộ tài liệu mẫu giả lập có sẵn tại `sample-documents/synthetic/` và bộ kiểm thử tự động có thể chạy bằng:

```powershell
python -m unittest discover -s tests -v
```

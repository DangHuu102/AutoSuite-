# HANDOFF — OfficeFlow (`001-office-to-pdf-batch`)

Cập nhật lần cuối: `2026-11-22`

## 1. Tóm tắt trạng thái bàn giao từ Codex & các vòng hoàn thiện

Khi kiểm tra workspace ban đầu:
- Codex đã hoàn thành mã nguồn của **Phase 1 → Phase 9** (`T001`–`T029`, `T031`–`T036`) cùng môi trường `.venv` (Python 3.12.16 + extra `desktop`), LibreOffice, Tesseract, Ollama (`0.40.16`), model `qwen3.5:4b` trong `.ollama-models/` và các tệp `.traineddata` trong `.tesseract/tessdata/`.
- Phần còn dở khi Codex dừng lại (`T030`, `T037`, cấu hình `configs/` & `pdf.ttf` cho `.tesseract/tessdata/`, bộ tài liệu mẫu `sample-documents/synthetic/` và `HANDOFF.md`) đã được tiếp nhận và hoàn thiện trọn vẹn, đồng thời mở rộng thêm **Phase 10 & Phase 11** (`T038`–`T046`) thông qua thảo luận đa mô hình AI (**Argon** + **Pro Architecture & Security Reviewer** + **Flash UX/CLI/QA Engineer** + **Ollama Local `qwen3.5:4b`**).

## 2. Kết quả thảo luận đa mô hình AI & các hạng mục Phase 10 đã hoàn tất

1. **Bảo cố bảo mật & độ tin cậy (Security & Reliability Hardening — `T039`)**:
   - `src/officeflow/staging.py`: Đưa `NamedTemporaryFile` vào bên trong khối `try ... finally` của `commit_staged_pdf()` để không bao giờ rò rỉ tệp `.officeflow-*.tmp` khi đĩa đầy hoặc mất kết nối; kiểm tra `STAGING_ROOT.is_symlink()`; hỗ trợ đường dẫn UNC trong `_rmtree_force()`; giới hạn độ dài tên tệp nguồn trong vùng tạm (`max_stem_length=48`) để tránh lỗi vượt `MAX_PATH` (260 ký tự) của Windows khi chạy LibreOffice/OCRmyPDF.
   - `src/officeflow/naming.py`: Giữ nguyên các phần mở rộng giả dạng số/phiên bản trong tên tệp như `Bao-cao.2026` hoặc `Hop-dong.v2` (chỉ cắt phần mở rộng khi thuộc danh sách định dạng tài liệu nguồn hoặc `.pdf`).
   - `src/officeflow/converter.py` & `src/officeflow/ocr.py`: Thêm `CREATE_NO_WINDOW` trên Windows để không nháy cửa sổ console đen khi chạy từ `officeflow-desktop`; tự động xoay đúng chiều ảnh chụp điện thoại qua `ImageOps.exif_transpose()`; bắt lỗi `Image.DecompressionBombError`; đếm ký tự văn bản thực (`.strip()`); và chọn đúng thư mục `tessdata` theo tổ hợp ngôn ngữ yêu cầu (`vie`, `eng`, `vie+eng`).
   - `src/officeflow/ai_filter.py`:
     - Bổ sung `"think": False` và `"num_predict": 300` cho Ollama `/api/chat` để dòng model suy luận `qwen3.5:4b` trả kết quả JSON theo schema chỉ trong vài giây thay vì bị timeout.
     - Chống prompt injection bằng cách lọc ký tự xuống dòng trong `current_name`, thoát thẻ đóng `</document>` (không phân biệt hoa/thường) trong văn bản trích xuất, làm sạch dấu phân cách đường dẫn (`/`, `\`) trong `suggested_basename` và giới hạn cứng `<= 12.000` ký tự sau khi ghép dòng.
     - Tách riêng lỗi `HTTPError` và `TimeoutError` khỏi lỗi kết nối mạng.
2. **Phân loại AI hàng loạt cả lô (Batch AI Classification — `T040`)**:
   - Thêm `BatchAIClassificationResult` và `classify_pdf_batch()` trong `src/officeflow/ai_filter.py`: kiểm tra quyền cloud (`allow_cloud` + `OPENAI_API_KEY`) hoặc danh sách model Ollama cục bộ 1 lần duy nhất trước khi chạy, xử lý tuần tự từng PDF kèm cô lập lỗi từng tệp.
   - Trên giao diện `src/officeflow/app.py`: tự động nạp danh sách model Ollama đã phát hiện, thêm nút **"Phân loại toàn bộ PDF trong lô"** có thanh tiến độ, nút **"Dùng tất cả tên gợi ý"**, nút **"Chọn tất cả" / "Bỏ chọn tất cả"**, và khóa nút gợi ý cũ khi người dùng đổi tiêu chí lọc.
   - Trên CLI `src/officeflow/cli.py`: lệnh `officeflow ai classify` nhận 1 hoặc nhiều tệp PDF cùng lúc (giữ nguyên định dạng JSON đơn cho 1 tệp và trả bảng tổng hợp JSON khi truyền nhiều tệp).
3. **Xuất báo cáo đối chiếu lô CSV/JSON an toàn (`src/officeflow/reporting.py` — `T041`)**:
   - Tạo mô-đun `src/officeflow/reporting.py` xuất báo cáo JSON và CSV chuẩn UTF-8 có BOM (`utf-8-sig`) hiển thị đúng tiếng Việt trên Microsoft Excel.
   - Không bao giờ ghi nội dung văn bản trích xuất, đường dẫn staging hay API key vào báo cáo; tự động trung hòa các ô bắt đầu bằng `=`, `+`, `-`, `@`, `\t`, `\r` để chống Excel Formula Injection; lưu tệp nguyên tử không ghi đè (`write_report_atomic`).
   - Hỗ trợ tải báo cáo CSV/JSON hoặc lưu trực tiếp vào thư mục đích trong màn hình tổng kết của `app.py` (đã bật `ALLOW_DOWNLOADS = True` trong `desktop.py`), và thêm cờ `--report-json`, `--report-csv`, `--dry-run` cho `officeflow convert`.
4. **Bộ tài liệu mẫu (`T038`) & Bộ kiểm thử tự động 27 tests (`T042`, `T046`)**:
   - Tạo bộ 5 tài liệu mẫu tiếng Việt tại `sample-documents/synthetic/` (`.docx`, `.xlsx` 2 trang tính, `.pptx` có slide ẩn, PDF scan 2 trang, ảnh `.png` 300 DPI + `README.md`).
   - Tạo bộ kiểm thử tự động trong `tests/` (`test_naming_and_validation.py`, `test_staging_batch_and_reporting.py`, `test_ai_filter_and_cli.py`, `test_integration_converters.py`, `test_phase11_merge_and_doctor.py`) đạt **27/27 PASS** (`python -m unittest discover -s tests -v`).
5. **Ghép nhiều ảnh scan thành 1 PDF nhiều trang có OCR (`T043`, `T044`) & Chẩn đoán môi trường `officeflow doctor` (`T045`)**:
   - Thêm `OCRProcessor.merge_images_to_pdf()` (kết hợp `img2pdf` + Pillow fallback + `OCRmyPDF`), tùy chọn `--merge-images NAME.pdf` trên CLI và tùy chọn *"Ghép các ảnh scan đã chọn thành một PDF nhiều trang"* trên giao diện Streamlit/Desktop. Nếu 1 ảnh trong nhóm bị lỗi, hệ thống tự động cô lập ảnh lỗi và vẫn ghép các ảnh hợp lệ còn lại.
   - Thêm mô-đun `src/officeflow/doctor.py` và lệnh `officeflow doctor [--json] [--strict]` để kiểm tra không gây tác dụng phụ toàn bộ runtime cục bộ (đọc `version.ini` của LibreOffice trong 0 ms không treo tiến trình, kiểm tra `ocrmypdf`, `tesseract`, `tessdata`, `staging`, `pywebview`, `ollama`, `openai` và ẩn tuyệt đối giá trị `OPENAI_API_KEY`).

## 3. Hiện trạng môi trường & đường dẫn công cụ trên máy

| Thành phần | Trạng thái | Đường dẫn / Ghi chú |
| --- | --- | --- |
| Python 3.12 venv | Sẵn sàng | `D:\OfficeFlow\.venv\Scripts\python.exe` (3.12.16, đã cài `.[desktop]`) |
| LibreOffice Desktop | Sẵn sàng | `C:\Program Files\LibreOffice\program\soffice.exe` |
| OCRmyPDF | Sẵn sàng | `D:\OfficeFlow\.venv\Scripts\ocrmypdf.exe` (17.13.0) |
| Tesseract OCR | Sẵn sàng | `C:\Program Files\Tesseract-OCR\tesseract.exe` (5.4.0.20240606) |
| Dữ liệu ngôn ngữ OCR | Sẵn sàng | `D:\OfficeFlow\.tesseract\tessdata` (`vie`, `eng`, `osd` + `configs`, `pdf.ttf`) |
| Ollama & Model local | Sẵn sàng | `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` (`0.40.16`), model `qwen3.5:4b` tại `D:\OfficeFlow\.ollama-models` |
| Bộ tài liệu mẫu | Sẵn sàng | `D:\OfficeFlow\sample-documents\synthetic\` (5 tệp mẫu + `README.md`) |
| Bộ kiểm thử tự động | 27/27 PASS | `D:\OfficeFlow\tests\` (`python -m unittest discover -s tests -v`) |

## 4. Hướng dẫn chạy nhanh & đẩy lên GitHub

```powershell
# 1. Kích hoạt môi trường ảo, chẩn đoán môi trường & chạy toàn bộ 27 bài kiểm thử tự động
.\.venv\Scripts\Activate.ps1
officeflow doctor
python -X utf8 -m unittest discover -s tests -v

# 2. Mở ứng dụng cửa sổ Desktop (WebView2) hoặc giao diện web cục bộ
officeflow-desktop
# hoặc: python -m streamlit run src/officeflow/app.py

# 3. Dùng CLI chuyển đổi bộ tài liệu mẫu kèm xuất báo cáo CSV/JSON hoặc ghép nhiều ảnh
officeflow convert .\sample-documents\synthetic\Bao-cao-hanh-chinh-2026.docx .\sample-documents\synthetic\Giay-de-nghi-thanh-toan.png --output-dir .\PDF --ocr-language vie --report-csv .\PDF\bao-cao.csv --report-json .\PDF\bao-cao.json
officeflow convert .\Trang-1.png .\Trang-2.png --output-dir .\PDF --ocr-language vie --merge-images Ho-so-ghep.pdf

# 4. Dùng CLI phân loại nhiều PDF cùng lúc bằng Ollama qwen3.5:4b
$env:OLLAMA_MODELS = "D:\OfficeFlow\.ollama-models"
officeflow ai models
officeflow ai classify .\PDF\Bao-cao-hanh-chinh-2026.pdf .\PDF\Giay-de-nghi-thanh-toan.pdf --provider ollama --model qwen3.5:4b --filter "Giữ tài liệu hành chính năm 2026"

# 5. Đẩy lên GitHub repository (nếu chưa gắn remote origin)
git remote add origin https://github.com/DangHuu102/OfficeFlow.git
git push -u origin master
```

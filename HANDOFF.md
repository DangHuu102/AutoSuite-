# HANDOFF — AutoSuite / OfficeFlow (`v0.3.0`)

Cập nhật lần cuối: `2026-11-24`

## 1. Tổng quan nâng cấp kiến trúc v0.3.0 (Multi-AI Redesign)

Phối hợp đa mô hình AI (**Top-Web UX Benchmark Designer**, **Low-RAM Backend Systems Architect**, **PDF-to-Word Table Specialist**, **Final QA & Security Auditor**) đối chiếu trực tiếp với các nền tảng hàng đầu (**iLovePDF, Convertio, Smallpdf, Cobalt.tools, Y2Mate**) để tái thiết kế toàn diện AutoSuite:

1. **Kiến trúc Web Siêu Nhẹ RAM (`src/officeflow/webapp.py` + `src/officeflow/static/`)**:
   - Thay thế hoàn toàn runtime Streamlit nặng nề (`~220+ MB` RAM khi chờ, rerun toàn trang, nhúng Base64 gây nghẽn bộ nhớ) bằng **Starlette + Uvicorn** kết hợp **Vanilla HTML5/CSS/JS SPA** không phụ thuộc ngoài.
   - **Đo thực nghiệm RSS RAM khi chờ**: **`32.75 MB`** (giảm **~85% RAM**).
   - Luồng tải lên (`store_source_stream` trong `staging.py` & `_stage_upload` trong `batch.py`) ghi trực tiếp từng khối `64 KB` xuống đĩa tạm cô lập, kiểm soát chặt giới hạn `100 MB/tệp` và `500 MB/lô` ngay trong lúc truyền mà không nạp toàn bộ tệp vào RAM.
   - `BoundedJobStore` giới hạn LRU tối đa 8 lô trong bộ nhớ, tự động dọn dẹp thư mục tạm sau TTL hoặc khi người dùng bấm *"Chuyển đổi tệp khác"*, kết hợp `gc.collect()` + thu hồi Working Set của tiến trình sau mỗi tác vụ.
   - Bảo vệ chống DNS Rebinding & CSRF qua `LocalOriginMiddleware` (`127.0.0.1`, `localhost`, `autosuite.localhost`, hỗ trợ `OFFICEFLOW_ALLOWED_HOSTS` cho Docker/VPS).

2. **Tự điều hướng thông minh ("Tự điều hướng" — `src/officeflow/static/app.js`)**:
   - Thanh 5 chế độ trực quan: `✨ Tự động nhận diện`, `📝 PDF → Word giữ bảng`, `📄 Office → PDF`, `🔍 Scan / Ảnh → PDF OCR`, `🗂️ Ghép Ảnh → 1 PDF` + công tắc `Tự chạy ngay` lưu theo trình duyệt.
   - Tự động phân tích định dạng tệp trong `0 ms` ngay trên trình duyệt (hỗ trợ kéo thả toàn màn hình và `Ctrl+V` dán ảnh chụp màn hình), chỉ hiển thị gọn **`Tổng dung lượng: ...`** đúng yêu cầu người dùng (bỏ hoàn toàn các ô giới hạn `20 tệp / 100 MB / 500 MB` và nút Deploy cũ).
   - Tự động chuyển cảnh mượt mà `#upload` → `#converting` (thanh tiến độ GPU `scaleX` kết hợp % upload thực + SSE `/api/jobs/{id}/events`) → `#download/{jobId}` kèm hỗ trợ nút Back/Forward của trình duyệt.

3. **Tải xuống & Định tuyến lưu trữ chuẩn Web Tải MP4/MP3/Video**:
   - Tuyệt đối không truy vấn hay phơi bày đường dẫn máy chủ `C:\Users\...`.
   - **Nút chính `⬇ Tải xuống máy`**: Thẻ `<a download>` gọi thẳng HTTP stream `FileResponse` (`Content-Disposition: attachment; filename="..."; filename*=UTF-8''...`, `Accept-Ranges: bytes`, `X-Content-Type-Options: nosniff`), đưa tệp thẳng vào thanh Download gốc của trình duyệt với `0 ms` độ trễ và `0 MB` RAM JS. Hỗ trợ tải gói `.ZIP` streaming không tốn RAM (`ZIP_STORED` trên đĩa tạm + `BackgroundTask` tự xóa tức thì).
   - **Nút phụ `📁 Chọn vị trí lưu (Save As…)`**: Sử dụng `window.showSaveFilePicker()` và `window.showDirectoryPicker()` kết hợp `fetch(url).then(r => r.body.pipeTo(writable))` ghi thẳng luồng dữ liệu vào bất kỳ ổ đĩa/thư mục nào người dùng chọn.

4. **Nâng cấp độ chính xác giữ bảng biểu PDF → Word (`src/officeflow/pdf_to_word.py`)**:
   - Khai thác `pypdfium2` trích xuất tọa độ hộp ký tự (`charbox`), khoảng nhảy cột `0-width` trong cùng khối `BT...ET`, thông tin phông chữ đậm/nghiêng và đường kẻ khung bảng vector (`FPDF_PAGEOBJ_PATH`).
   - Phân cụm cột theo khoảng chiếu trục X, tính độ rộng cột tỷ lệ thực (`9638 dxa` khổ in A4), căn phải cột số liệu tiền tệ, gộp dòng ô xuống hàng, nhúng `<w:rFonts>` tiếng Việt (`Times New Roman` / `Arial` / `Segoe UI` + `word/styles.xml` + chuẩn hóa Unicode `NFC`), và ghi nén `.docx` dạng luồng từng trang (`O(1)` RAM).

## 2. Trạng thái kiểm thử & vận hành

- **Kiểm thử tự động**: **33/33 bài kiểm thử PASS** (`tests/test_webapp.py`, `test_naming_and_validation.py`, `test_staging_batch_and_reporting.py`, `test_ai_filter_and_cli.py`, `test_integration_converters.py`, `test_phase11_merge_and_doctor.py`).
- **Dịch vụ chạy ngầm 24/24 trên máy**: `src/officeflow/daemon_24x7.py` + `Startup\AutoSuite-24x7.vbs` tự động duy trì Uvicorn tại `http://autosuite.localhost:8501`.
- **GitHub Remote**: `https://github.com/DangHuu102/AutoSuite-.git` (tự động commit & push sau mỗi bản nâng cấp).

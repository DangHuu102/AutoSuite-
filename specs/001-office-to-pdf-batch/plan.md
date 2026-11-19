# Implementation Plan: Chuyển tài liệu văn phòng và bản scan sang PDF theo lô

Branch: Chưa tạo | Date: 2026-11-18 | Spec: [spec.md](spec.md)

Input: Đặc tả tính năng tại [spec.md](spec.md)

## Summary

Xây dựng ứng dụng cục bộ cho nhân viên văn phòng chọn tối đa 20 tệp .docx, .xlsx, .pptx, PDF scan và ảnh scan; kiểm tra tên/định dạng, tạo PDF tạm (thêm lớp chữ OCR cho scan) để xem trước, rồi lưu các tệp đã duyệt. Bản đầu xử lý tuần tự, tiếp tục sau lỗi từng tệp và không ghi đè âm thầm.

Microsoft Office đã có chức năng xuất từng tài liệu sang PDF; giá trị của MVP là xử lý theo lô, xử lý tên trùng, báo lỗi riêng, OCR PDF/ảnh scan tại chỗ và có bước duyệt kết quả. Dùng LibreOffice cho Office, OCRmyPDF/Tesseract cho scan, Python điều phối và Streamlit làm giao diện localhost. Chi tiết lựa chọn và giới hạn nằm trong [research.md](research.md).

## Technical Context

Language/Version: Python 3.12 (đề xuất cho prototype)

Primary Dependencies: Streamlit với tiện ích xem PDF; LibreOffice CLI cho Office; OCRmyPDF, Tesseract và gói ngôn ngữ OCR cục bộ cho PDF/ảnh scan; pypdf để kiểm tra/trích văn bản PDF; Ollama HTTP API loopback cho gợi ý AI tùy chọn

Storage: Tệp nguồn được giữ nguyên; PDF tạm ở thư mục phiên cục bộ; chỉ PDF được xác nhận mới vào thư mục đích; không có cơ sở dữ liệu

Testing: Hướng dẫn xác nhận thủ công bằng bộ tài liệu giả lập tại [quickstart.md](quickstart.md); chưa tạo hoặc chạy bộ kiểm thử tự động

Target Platform: Windows 11 trước tiên, dựa trên môi trường làm việc hiện có

Project Type: Ứng dụng cục bộ có giao diện web chỉ truy cập qua loopback

Performance Goals: Chuyển 20 tài liệu Office trong tối đa 5 phút trên máy tham chiếu; OCR scan đo riêng vì thời gian phụ thuộc số trang/độ phân giải. Đây là mục tiêu ban đầu cần đo trong prototype

Constraints: Nhận .docx, .xlsx, .pptx, .pdf và .png/.jpg/.jpeg/.tif/.tiff/.bmp; không nhận tệp Office macro-enabled hoặc định dạng cũ; giới hạn 20 tệp và 500 MB mỗi lô; OCR chạy cục bộ; AI tùy chọn chỉ dùng model Ollama local; một ảnh tạo một PDF riêng; xem PDF trước khi lưu; cần LibreOffice và OCRmyPDF/Tesseract cùng gói ngôn ngữ; bố cục Office có thể khác Microsoft Office, độ chính xác OCR phụ thuộc chất lượng scan

Scale/Scope: Một người dùng và tối đa 20 tệp mỗi lô trong MVP; một PDF cho mỗi tệp nguồn hợp lệ; không xử lý đồng thời nhiều lô

## Constitution Check

GATE: Không có tệp constitution trong workspace nên không có nguyên tắc dự án riêng để áp dụng.

- Riêng tư: ứng dụng chỉ lắng nghe trên localhost, tắt thống kê sử dụng, không gọi dịch vụ AI ngoài; nội dung phân loại chỉ gửi đến Ollama qua loopback nếu người dùng chủ động bật.
- An toàn dữ liệu: phù hợp khi nguồn chỉ đọc, đầu ra được tạo trong vùng tạm, và chỉ chuyển sang thư mục đích sau xác nhận.
- Độ tin cậy: phù hợp khi lỗi được theo dõi từng tệp, không ghi đè và người dùng duyệt PDF trước khi lưu.
- Phạm vi: phù hợp khi dùng LibreOffice cho Office và OCRmyPDF/Tesseract cho scan; không thêm OCR sang Office có thể sửa, ghép ảnh, tách PDF hoặc sửa nội dung.

**Gate trước Phase 0**: Pass theo các ràng buộc của spec.

## Phase 0: Research

Đã đối chiếu khả năng xuất PDF của Office, giao diện cục bộ nhiều tệp và bộ chuyển đổi LibreOffice. Quyết định cùng phương án thay thế được ghi trong [research.md](research.md). Không còn câu hỏi kỹ thuật bắt buộc phải giải quyết trước khi thiết kế.

## Phase 1: Design & Contracts

- Mô hình dữ liệu và trạng thái lô: [data-model.md](data-model.md)
- Hợp đồng đầu vào/đầu ra và hành vi giao diện: [contracts/batch-conversion.md](contracts/batch-conversion.md)
- Hướng dẫn xác nhận thủ công: [quickstart.md](quickstart.md)

### Constitution Re-check

- Giao diện không mở cổng mạng LAN; chỉ phục vụ localhost.
- Tắt thu thập thống kê sử dụng và không tích hợp dịch vụ đám mây.
- Ollama là lựa chọn bổ sung chạy cục bộ; lọc AI không được làm thay đổi quyết định lưu tự động.
- Xóa tệp tạm khi xác nhận lưu hoặc hủy; OCR không gửi dữ liệu ra ngoài máy.
- Giữ nguồn không đổi, không tự ghi đè, và yêu cầu duyệt PDF.

**Gate sau Phase 1**: Pass với các giới hạn trên. Cần thử độ trung thực bố cục với tệp Word, Excel, PowerPoint đại diện trước khi xác nhận pilot.

## Project Structure

### Documentation (this feature)

    specs/001-office-to-pdf-batch/
    ├── spec.md
    ├── plan.md
    ├── research.md
    ├── data-model.md
    ├── quickstart.md
    ├── checklists/
    │   └── requirements.md
    └── contracts/
        └── batch-conversion.md

### Source Code

    src/
    └── officeflow/
        ├── app.py
        ├── ai_filter.py
        ├── batch.py
        ├── models.py
        ├── validation.py
        ├── naming.py
        ├── converter.py
        ├── ocr.py
        ├── staging.py
        └── messages_vi.py

    sample-documents/
    └── synthetic/

Structure Decision: Một ứng dụng cục bộ duy nhất; Streamlit xử lý giao diện, các mô-đun Python điều phối kiểm tra/tên/vòng đời lô, và LibreOffice là bộ chuyển đổi ngoài. Chưa tách frontend/backend hay thêm database vì MVP chỉ có một người dùng và dữ liệu tạm theo phiên.

## Complexity Tracking

Không có vi phạm constitution hoặc thành phần bổ sung cần biện minh.

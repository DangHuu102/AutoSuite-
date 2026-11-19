# Research: Chuyển tài liệu văn phòng và bản scan sang PDF theo lô

## Bối cảnh và giới hạn

Người dùng đã chọn luồng cho nhân viên văn phòng: nhiều tệp Word, Excel, PowerPoint, PDF scan và ảnh scan thành PDF; tự đặt tên; OCR PDF/ảnh scan và kiểm tra trước khi lưu. Workspace chưa có constitution, nên các lựa chọn kỹ thuật dưới đây áp dụng cho prototype Windows cục bộ.

## Quyết định 1: Tập trung vào batch PDF, không gộp các hướng chuyển đổi khác

**Decision**: MVP nhận .docx, .xlsx, .pptx, PDF và ảnh scan; mỗi tệp nguồn hợp lệ tạo một PDF. PDF/ảnh scan được thêm lớp chữ OCR để tìm kiếm, nhưng không chuyển thành tài liệu Office có thể sửa.

**Rationale**: Office đã cung cấp chức năng xuất từng tài liệu sang PDF. Sản phẩm cần tạo giá trị bằng việc chọn nhiều tệp, đặt tên nhất quán, phát hiện xung đột, báo lỗi theo từng tệp và tổng kết lô. [Microsoft Support: Save or convert Office files to PDF](https://support.microsoft.com/en-us/office/collab-files/save-or-convert-to-pdf-or-xps-in-office-desktop-apps)

**Alternatives considered**:

- DOCX sang PPTX: đây là chuyển nội dung thành slide, cần chọn lọc và dàn nội dung; không phải chuyển định dạng giữ nguyên bố cục. Microsoft mô tả luồng Word→PowerPoint dựa trên phần văn bản tóm tắt, và trang hỗ trợ hiện ghi tính năng này đang bị ngừng. [Microsoft Support: Export Word documents to PowerPoint](https://support.microsoft.com/en-gb/word/export-word-documents-to-powerpoint-presentations)
- DOCX sang Excel: chỉ rõ ràng khi tài liệu chứa bảng có cấu trúc; là tác vụ trích xuất dữ liệu khác với xuất PDF.
- OCR PDF sang Office: biến thể kỹ thuật khác, phụ thuộc chất lượng scan và cần tái cấu trúc nội dung; vẫn ngoài phạm vi.

## Quyết định 2: Dùng LibreOffice CLI làm bộ chuyển đổi đầu tiên

**Decision**: Chạy LibreOffice cục bộ ở chế độ không giao diện để xuất PDF vào thư mục tạm.

**Rationale**: LibreOffice có bộ lọc mở các định dạng Word, Excel, PowerPoint và hỗ trợ lệnh dòng lệnh xuất PDF trên Windows. Các tham số PDF có thể điều khiển trang, ghi chú và slide ẩn. [LibreOffice: Microsoft Office formats](https://help.libreoffice.org/latest/en-US/text/shared/guide/ms_user.html?DbPAR=IMPRESS&System=WIN), [LibreOffice: PDF CLI parameters](https://help.libreoffice.org/latest/en-GB/text/shared/guide/pdf_params.html?DbPAR=CALC&System=MAC), [LibreOffice: conversion filter names](https://help.libreoffice.org/latest/gu/text/shared/guide/convertfilters.html)

**Alternatives considered**:

- Tự động điều khiển Word/Excel/PowerPoint: có thể gần với kết quả Office hơn trên máy có Office, nhưng Microsoft không khuyến nghị và không hỗ trợ tự động hóa Office từ ứng dụng không tương tác vì nguy cơ treo hoặc chạy không ổn định. [Microsoft Learn: unattended Office automation](https://learn.microsoft.com/en-us/office/client-developer/integration/considerations-unattended-automation-office-microsoft-365-for-unattended-rpa)
- Dịch vụ chuyển đổi đám mây: không phù hợp với ràng buộc MVP xử lý cục bộ, và tệp văn phòng có thể chứa thông tin nội bộ.

**Risk**: LibreOffice có thể dàn trang khác Microsoft Office do khác phiên bản hoặc thiếu phông chữ. Vì vậy phải kiểm tra PDF của tài liệu mẫu, đặc biệt bảng tính có vùng in, slide ẩn và phông tiếng Việt; không tuyên bố giữ nguyên pixel cho mọi tệp.

## Quyết định 3: Dùng OCRmyPDF và Tesseract cho PDF/ảnh scan

**Decision**: Chạy OCRmyPDF cục bộ cho PDF scan và ảnh đầu vào; giữ ảnh/trang gốc và thêm lớp chữ vô hình. Dùng ngôn ngữ `vie` mặc định, cho phép `eng` hoặc `vie+eng` khi gói ngôn ngữ đã có.

**Rationale**: OCRmyPDF thêm lớp chữ tìm kiếm được vào PDF scan; với ảnh đơn, công cụ có thể tạo một PDF và OCR cùng lúc. Nhiều ảnh được xử lý thành nhiều PDF riêng theo quy tắc một PDF cho mỗi nguồn. [OCRmyPDF: introduction](https://ocrmypdf.readthedocs.io/en/stable/introduction.html), [OCRmyPDF: OCR images](https://ocrmypdf.readthedocs.io/en/stable/cookbook.html)

**Dependencies**: Cài OCRmyPDF, Tesseract và gói ngôn ngữ cần dùng cục bộ. Trên Windows, tài liệu OCRmyPDF hiện hướng dẫn cài Tesseract 64-bit; Ghostscript hoặc pypdfium2 dùng cho raster hóa/đường xử lý PDF tùy cấu hình. [OCRmyPDF: Windows installation](https://ocrmypdf.readthedocs.io/en/stable/installation.html)

**Risk**: Độ chính xác phụ thuộc độ phân giải, độ nghiêng, chất lượng in và ngôn ngữ. Chữ viết tay không được đảm bảo; người dùng phải xem PDF trước khi lưu. Nhiều ảnh không được ghép thành một PDF trong MVP.

## Quyết định 4: Giao diện cục bộ bằng Streamlit

**Decision**: Dùng Streamlit để tạo giao diện Python mở trong trình duyệt trên cùng máy; lắng nghe tại 127.0.0.1, giới hạn tệp nhiều loại, tắt usage stats và không dùng dịch vụ ngoài.

**Rationale**: Streamlit hỗ trợ chọn nhiều tệp; tiện ích PDF có thể hiển thị tệp xem trước. Giao diện và bộ chuyển đổi đều chạy trên máy người dùng. [Streamlit file uploader](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader), [Streamlit PDF viewer](https://docs.streamlit.io/develop/api-reference/media/st.pdf), [Streamlit local server configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)

**Alternatives considered**:

- Giao diện desktop native: tránh local web server nhưng tăng công sức giao diện và đóng gói cho prototype.
- Chỉ dùng dòng lệnh: ít công sức hơn nhưng không phù hợp người dùng văn phòng cần kiểm tra tên, trạng thái và PDF xem trước.

**Risk**: File uploader của Streamlit có giới hạn mặc định theo từng tệp và nội dung đi vào tiến trình ứng dụng cục bộ. Giới hạn lô và dọn tệp tạm cần được xác định; cấu hình phải không cho truy cập từ LAN và tắt telemetry.

## Quyết định 5: Chọn tệp rõ ràng, xử lý tuần tự và staging trước khi commit

**Decision**: Người dùng chọn các tệp cụ thể; app không quét thư mục đệ quy. Mỗi tệp được kiểm tra rồi chuyển đổi tuần tự vào thư mục staging. Sau khi người dùng xem tên và PDF, chỉ các tệp được xác nhận mới chuyển tới thư mục đích.

**Rationale**: Giảm nguy cơ xử lý nhầm tài liệu, giữ lỗi từng tệp tách biệt, và không ghi nửa chừng vào thư mục kết quả chính.

**Alternatives considered**:

- Chuyển đổi trực tiếp vào thư mục đích: đơn giản hơn nhưng để lại kết quả dở dang nếu lô bị hủy.
- Quét toàn bộ thư mục con: tiện cho lô lớn nhưng có thể lấy nhầm tệp không định chuyển đổi.

## Quyết định 6: Đặt tên và lỗi

**Decision**: Tên mặc định lấy từ tên gốc; nếu trùng với tệp trong lô hoặc thư mục đích thì thêm hậu tố tăng dần, hiển thị trước khi lưu. Tệp lỗi không làm dừng các tệp còn lại.

**Rationale**: Tạo kết quả có thể dự đoán, tránh mất dữ liệu do ghi đè và hỗ trợ làm lại riêng tệp lỗi.

## Những giả định còn cần đo

- 20 tệp mỗi lô và 5 phút là mục tiêu thử ban đầu, không phải hiệu năng đã xác nhận.
- Tệp thật của người dùng có thể dùng font, vùng in, liên kết hoặc thiết lập PowerPoint mà mẫu giả lập chưa đại diện.
- Bộ tài liệu đại diện cần có cả tệp Việt ngữ, Excel nhiều trang tính, slide ẩn, tài liệu có mật khẩu và tên trùng.

## Quyết định 7: AI phân loại chỉ chạy cục bộ và chỉ đưa ra gợi ý

**Decision**: Tích hợp tùy chọn Ollama qua địa chỉ loopback cố định `127.0.0.1:11434`. Chỉ liệt kê model đã cài tại máy, loại identifier có nhãn cloud/remote, trích tối đa 8 trang đầu và 12.000 ký tự PDF, xử lý từng tệp một trong timeout hữu hạn và yêu cầu đầu ra JSON có schema. Trước khi áp dụng gợi ý giữ/bỏ qua vào ô chọn, người dùng phải xác nhận đã xem kết quả; bước duyệt PDF và xác nhận lưu luôn được giữ.

**Rationale**: Người dùng cần lọc một lô tài liệu nhưng nội dung có thể nhạy cảm. Không gửi tệp ra nhà cung cấp AI, không phụ thuộc mạng/API key và không giao quyền xóa hoặc lưu tài liệu cho mô hình. Khi Ollama không có, luồng chuyển PDF/OCR tiếp tục hoạt động.

**Alternative considered**: API AI cloud có thể cho kết quả tốt hơn trên máy yếu nhưng sẽ gửi trích đoạn tài liệu ra ngoài thiết bị, phát sinh tài khoản/chi phí và cần xin quyết định quyền riêng tư riêng. Không dùng trong MVP.

**Risk**: Phân loại và tên do AI tạo có thể sai hoặc bị ảnh hưởng bởi nội dung prompt injection trong tài liệu. Giới hạn văn bản đầu vào, coi nội dung là dữ liệu không đáng tin cậy, hiển thị đó là gợi ý, và yêu cầu người dùng duyệt từng tệp.

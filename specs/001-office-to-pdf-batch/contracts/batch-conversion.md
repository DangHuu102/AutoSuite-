# Batch Conversion Contract

## Input

- Mỗi lô nhận tối đa 20 tệp do người dùng chọn rõ ràng.
- Tổng dung lượng một lô tối đa 500 MB; mỗi tệp tải qua giao diện tối đa 100 MB.
- Office hỗ trợ .docx, .xlsx, .pptx; scan hỗ trợ .pdf, .png, .jpg, .jpeg, .tif, .tiff và .bmp.
- MVP không nhận .doc, .xls, .ppt, .docm, .xlsm, .pptm, GIF, HEIC hoặc TIFF nhiều khung.
- Tệp phải đọc được và không bị khóa mật khẩu.
- Tệp nguồn luôn được giữ nguyên.

## Conversion behavior

- Mỗi tệp nguồn hợp lệ tạo tối đa một PDF.
- PDF scan giữ hình ảnh trang và thêm lớp chữ OCR. Mỗi ảnh đơn tạo một PDF riêng; nhiều ảnh không ghép chung.
- OCR dùng ngôn ngữ đã chọn (mặc định tiếng Việt) và chạy trên máy người dùng; thiếu gói ngôn ngữ phải báo lỗi riêng.
- Trang PDF đã có chữ được giữ nguyên, các trang scan mới được OCR khi có thể.
- Lỗi ở một tệp không dừng chuyển đổi các tệp khác.
- Tệp được xử lý vào thư mục staging cục bộ trước.
- Dùng thiết lập trang/in hiện có của tài liệu. Tệp Excel có thể có nhiều trang; người dùng cần duyệt PDF.
- PowerPoint xuất các slide trình chiếu thông thường; không xuất trang ghi chú hoặc slide ẩn theo mặc định.
- Tên PDF mặc định là tên cơ sở của tệp nguồn cộng phần mở rộng .pdf.
- Nếu tên trùng, hệ thống thêm hậu tố tăng dần và hiển thị tên cuối trước khi lưu.

## User confirmation

- Trước khi lưu, người dùng thấy tên nguồn, loại tệp, tên PDF dự kiến và lỗi/cảnh báo.
- Người dùng mở được PDF staging để kiểm tra.
- Với PDF/ảnh scan, giao diện nêu ngôn ngữ OCR; người dùng cần kiểm tra nội dung nhận dạng vì chất lượng tùy thuộc scan.
- Người dùng xác nhận lô trước khi bất kỳ PDF nào được chuyển vào thư mục đích.
- Hủy lô xóa PDF staging và không ảnh hưởng đến nguồn hoặc tệp có sẵn ở thư mục đích.
- Gợi ý AI (nếu được bật) hiển thị riêng theo PDF; trước khi áp dụng keep/skip hàng loạt, người dùng phải đánh dấu rằng họ đã xem các gợi ý.

## Results

- Trạng thái theo từng tệp: đã chuyển, lỗi, bỏ qua hoặc cần xem lại.
- Kết quả lưu trong thư mục người dùng chọn.
- Bảng tổng kết trong giao diện nêu số lượng và lỗi; không lưu nội dung PDF hay văn bản nguồn trong log.
- Sau khi lô kết thúc, ứng dụng xóa bản tạm.

## Privacy and access

- Ứng dụng chỉ phục vụ giao diện cho máy hiện tại.
- Không gửi tệp, nội dung hoặc tên tệp tới dịch vụ ngoài.
- OCRmyPDF, Tesseract và gói ngôn ngữ được cài cục bộ; không gọi OCR đám mây.
- Khi người dùng chủ động yêu cầu phân loại, chỉ gửi tối đa 8 trang và 12.000 ký tự trích PDF tới model AI cục bộ qua loopback; chỉ xử lý từng PDF một với timeout hữu hạn.
- HTTP proxy bị tắt và redirect bị từ chối; không dùng model cloud/remote. Gợi ý AI không tự bỏ chọn, xóa hoặc lưu.
- Dữ liệu tạm chỉ tồn tại trong phiên xử lý.

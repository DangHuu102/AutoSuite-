# Feature Specification: Chuyển tài liệu văn phòng và bản scan sang PDF theo lô

**Feature Branch**: Chưa tạo (workspace hiện không có hook tạo nhánh)

**Created**: 2026-11-18

**Status**: Draft

**Input**: Người dùng chọn luồng cho nhân viên văn phòng: chuyển Word, Excel, PowerPoint, PDF scan và ảnh scan sang PDF theo lô; tự đặt tên, tạo lớp chữ OCR cho đầu vào scan và kiểm tra trước khi lưu.

## Product Context

Word, Excel và PowerPoint đã có chức năng lưu hoặc xuất từng tài liệu sang PDF. MVP này xử lý nhiều tài liệu trong một lần, đồng thời nhận PDF scan và ảnh để tạo PDF có lớp chữ tìm kiếm được. Người dùng kiểm tra từng kết quả trước khi lưu. [Microsoft Support: Save or convert Office files to PDF](https://support.microsoft.com/en-us/office/collab-files/save-or-convert-to-pdf-or-xps-in-office-desktop-apps)

## User Scenarios & Testing

### User Story 1 - Chuyển một nhóm tệp sang PDF (Priority: P1)

Nhân viên văn phòng có nhiều tài liệu Word, bảng tính Excel hoặc bài trình chiếu PowerPoint muốn tạo PDF riêng cho từng tệp trong một lượt.

**Why this priority**: Đây là tác vụ chính và đầu ra rõ ràng: mỗi tệp nguồn hợp lệ tạo một PDF.

**Independent Test**: Chọn một nhóm nhỏ gồm ít nhất một tệp .docx, một .xlsx và một .pptx. Xác nhận mỗi tệp nguồn tạo được một PDF mở được và tệp nguồn không bị thay đổi.

**Acceptance Scenarios**:

1. **Given** một nhóm tệp có định dạng được hỗ trợ, **When** người dùng bắt đầu chuyển đổi, **Then** hệ thống xử lý từng tệp và hiển thị trạng thái riêng cho mỗi tệp.
2. **Given** một tệp nguồn chuyển đổi thành công, **When** người dùng xem kết quả, **Then** có đúng một PDF tương ứng với tệp đó.
3. **Given** có tệp lỗi trong nhóm, **When** các tệp khác vẫn hợp lệ, **Then** hệ thống tiếp tục xử lý các tệp hợp lệ và nêu rõ tệp lỗi.

---

### User Story 2 - Kiểm tra tệp và tên PDF trước khi lưu (Priority: P1)

Người dùng muốn xem tệp nào được hỗ trợ, tên PDF dự kiến và các lỗi có thể xử lý trước khi đưa kết quả vào thư mục chính thức.

**Why this priority**: Tên trùng, tài liệu có mật khẩu hoặc thiết lập in không phù hợp có thể làm mất kết quả hoặc tạo PDF không dùng được.

**Independent Test**: Chọn hai tệp trùng tên từ hai thư mục khác nhau cùng một tệp không hỗ trợ. Xác nhận danh sách kiểm tra báo lỗi và không có tệp nào bị ghi đè.

**Acceptance Scenarios**:

1. **Given** người dùng đã chọn tệp, **When** danh sách được kiểm tra, **Then** hệ thống hiển thị loại tệp, tên PDF dự kiến và cảnh báo theo từng tệp.
2. **Given** tệp có tên đầu ra trùng với một tệp trong lô hoặc thư mục đích, **When** hệ thống kiểm tra, **Then** hệ thống đề xuất tên khác và không ghi đè âm thầm.
3. **Given** PDF tạm đã được tạo, **When** người dùng mở phần xem trước, **Then** họ có thể kiểm tra trang tính Excel, trang Word hoặc slide PowerPoint trước khi xác nhận lưu.
4. **Given** người dùng hủy trước khi xác nhận lưu, **When** lô kết thúc, **Then** các PDF tạm bị xóa và tệp nguồn giữ nguyên.

---

### User Story 3 - Lưu và đối chiếu kết quả của lô (Priority: P2)

Người dùng muốn lưu các PDF đã duyệt vào thư mục đích và biết tệp nào thành công, thất bại hoặc bị bỏ qua.

**Why this priority**: Bảng tổng kết giúp người dùng hoàn tất công việc và xử lý lại đúng tệp lỗi mà không phải đoán.

**Independent Test**: Chuyển một lô có tệp thành công và tệp lỗi; xác nhận PDF thành công được lưu, lỗi được báo theo tên tệp và báo cáo lô phản ánh đúng số lượng.

**Acceptance Scenarios**:

1. **Given** người dùng đã duyệt tên và PDF xem trước, **When** họ xác nhận lưu, **Then** các PDF được ghi vào thư mục đích đã chọn.
2. **Given** lô đã kết thúc, **When** người dùng xem tổng kết, **Then** có số tệp nguồn, số PDF thành công, số tệp lỗi và thông báo lỗi theo tệp.
3. **Given** người dùng chạy lại một tệp đã lỗi sau khi sửa tệp nguồn, **When** họ tạo lô mới, **Then** kết quả của lô cũ không bị ghi đè âm thầm.

---

### User Story 4 - OCR PDF scan và ảnh thành PDF có thể tìm kiếm (Priority: P1)

Nhân viên văn phòng có PDF scan hoặc ảnh chụp giấy tờ muốn tạo PDF giữ hình ảnh gốc và có thể tìm kiếm, chọn, sao chép phần chữ được nhận diện.

**Why this priority**: Hồ sơ scan thường không có lớp chữ; OCR giúp người dùng tìm nội dung mà không biến tệp thành tài liệu Office có thể chỉnh sửa.

**Independent Test**: Chọn một PDF scan nhiều trang và một ảnh có chữ in rõ. Xác nhận mỗi nguồn tạo một PDF xem được, có lớp chữ OCR theo ngôn ngữ đã chọn; tệp ảnh/PDF nguồn giữ nguyên.

**Acceptance Scenarios**:

1. **Given** một PDF scan hợp lệ, **When** người dùng chọn chuyển đổi, **Then** kết quả giữ nội dung trang và thêm lớp chữ có thể tìm kiếm.
2. **Given** một ảnh scan hợp lệ, **When** người dùng chọn chuyển đổi, **Then** hệ thống tạo một PDF cho ảnh đó và thêm lớp chữ OCR.
3. **Given** lô có PDF/ảnh lỗi, **When** các nguồn khác hợp lệ, **Then** hệ thống báo lỗi theo tệp và tiếp tục các nguồn còn lại.
4. **Given** ngôn ngữ OCR cần dùng không có trên máy, **When** người dùng bắt đầu chuyển đổi, **Then** hệ thống báo rõ ngôn ngữ cần cài và không báo thành công giả.

---

### User Story 5 - Nhờ AI gợi ý lọc và đặt tên (Priority: P2)

Nhân viên văn phòng muốn phân loại một lô tài liệu theo tiêu chí của mình, để nhanh chóng nhận ra tệp nên giữ, bỏ qua hoặc xem lại; quyết định lưu cuối cùng vẫn do người dùng đưa ra.

**Why this priority**: Phân loại giúp xử lý lô lớn nhanh hơn nhưng không được làm mất tệp do AI nhận định sai.

**Independent Test**: Với Ollama cục bộ hoặc OpenAI API đã cấu hình, yêu cầu lọc một lô PDF theo tiêu chí cụ thể; xác nhận từng gợi ý có nhóm, lý do và tên đề xuất, không tệp nào bị tự bỏ chọn hoặc lưu.

**Acceptance Scenarios**:

1. **Given** Ollama đang chạy và có model local, **When** người dùng nhập yêu cầu lọc và chạy AI, **Then** hệ thống phân tích phần chữ có giới hạn trong PDF tạm và hiển thị gợi ý theo từng tệp.
2. **Given** model không chạy, PDF không có lớp chữ hoặc model trả dữ liệu sai, **When** người dùng yêu cầu phân loại, **Then** hệ thống báo rõ theo tệp và chức năng chuyển đổi/lưu cơ bản vẫn dùng được.
3. **Given** AI gợi ý bỏ qua hoặc giữ một PDF, **When** kết quả được hiển thị, **Then** hệ thống không tự đổi lựa chọn lưu, xóa hoặc lưu tệp; người dùng phải tự áp dụng gợi ý và xác nhận.
4. **Given** người dùng chọn Ollama, **When** nội dung được phân tích, **Then** văn bản được gửi tới Ollama tại `127.0.0.1` và không gọi model cloud.
5. **Given** người dùng chọn OpenAI API, đã đặt API key và đồng ý, **When** nội dung được phân tích, **Then** chỉ đoạn văn bản có giới hạn được gửi tới Responses API; tệp PDF không được tải lên.
6. **Given** thiếu API key hoặc người dùng chưa đồng ý gửi dữ liệu, **When** họ dùng AI cloud, **Then** yêu cầu bị chặn và chuyển đổi/OCR cục bộ vẫn hoạt động.

### User Story 6 - Dùng OfficeFlow từ desktop và CLI (Priority: P1)

Nhân viên văn phòng muốn mở OfficeFlow như ứng dụng Windows riêng hoặc xử lý tệp qua CLI để tích hợp vào quy trình làm việc.

**Independent Test**: Khởi chạy cửa sổ desktop, đóng nó và xác nhận dịch vụ local tự tắt; sau đó dùng CLI để chuyển một lô tệp và nhận JSON từ lệnh AI, không ghi đè âm thầm.

**Acceptance Scenarios**:

1. **Given** gói desktop đã cài và WebView2 Runtime sẵn có, **When** người dùng chạy `officeflow-desktop`, **Then** giao diện mở trong cửa sổ riêng và máy chủ chỉ lắng nghe loopback.
2. **Given** người dùng chỉ rõ các tệp và thư mục đầu ra, **When** họ chạy `officeflow convert`, **Then** hệ thống chuyển từng tệp hợp lệ, tiếp tục sau lỗi và báo tên đầu ra.
3. **Given** người dùng chạy `officeflow ai classify --provider openai --allow-cloud`, **When** API key có sẵn, **Then** CLI gọi API và trả gợi ý JSON; nếu thiếu cờ xác nhận, không gửi nội dung.

### Edge Cases

- Tệp có phần mở rộng được hỗ trợ nhưng nội dung sai định dạng, bị hỏng hoặc đặt mật khẩu.
- Tệp macro-enabled như .docm, .xlsm, .pptm hoặc định dạng Office cũ.
- Nhiều tệp từ các thư mục khác nhau có cùng tên.
- Thư mục đích đã có PDF cùng tên.
- Tên tệp hoặc thư mục có dấu tiếng Việt, ký tự đặc biệt hoặc đường dẫn dài.
- Tệp Excel có nhiều trang tính, vùng in, trang tính ẩn hoặc nội dung vượt trang.
- Tệp PowerPoint có slide ẩn, ghi chú hoặc khổ trang tùy chỉnh.
- PDF scan có trang đã chứa chữ, PDF bị mã hóa, ảnh độ phân giải thấp hoặc ảnh nhiều trang TIFF.
- PDF có chữ ký số; thêm OCR có thể làm chữ ký mất hiệu lực nên phải báo lỗi và không tuyên bố chữ ký còn hợp lệ.
- Tổng dung lượng các tệp trong lô vượt ngưỡng 500 MB hoặc tệp đơn vượt giới hạn 100 MB của giao diện.
- Gói ngôn ngữ OCR không được cài, chữ viết tay hoặc scan mờ/nghiêng.
- Tệp Word dùng phông chữ không có trên máy hoặc có bình luận/theo dõi thay đổi.
- Không đủ dung lượng đĩa, người dùng mất kết nối tới thư mục đích, hoặc đóng ứng dụng giữa lô.
- Một tệp không chuyển đổi được nhưng các tệp còn lại hợp lệ.

## Requirements

### Functional Requirements

- **FR-001**: Hệ thống MUST nhận tối đa 20 tệp, tổng dung lượng không vượt quá 500 MB trong một lô, và hỗ trợ .docx, .xlsx, .pptx, .pdf, .png, .jpg, .jpeg, .tif, .tiff và .bmp.
- **FR-002**: MVP MUST chỉ xử lý các tệp người dùng chọn rõ ràng; không tự quét đệ quy toàn bộ thư mục.
- **FR-003**: Hệ thống MUST tạo tối đa một PDF cho mỗi tệp nguồn hợp lệ và MUST giữ nguyên tệp nguồn. Với ảnh, mỗi ảnh tạo một PDF riêng; MVP không ghép nhiều ảnh thành một PDF.
- **FR-004**: Hệ thống MUST đề xuất tên PDF bằng tên gốc của tệp nguồn và cho người dùng xem hoặc chỉnh tên trước khi lưu.
- **FR-005**: Hệ thống MUST phát hiện xung đột tên trong lô và trong thư mục đích; hệ thống MUST không ghi đè tệp hiện có nếu người dùng chưa xác nhận cách xử lý.
- **FR-006**: Hệ thống MUST kiểm tra phần mở rộng, khả năng đọc tệp và kết quả chuyển đổi/OCR; tệp không hỗ trợ, bị hỏng, có mật khẩu hoặc lỗi MUST được báo theo tên tệp.
- **FR-007**: Hệ thống MUST tiếp tục xử lý các tệp hợp lệ nếu một tệp khác trong cùng lô bị lỗi.
- **FR-008**: Hệ thống MUST tạo PDF trong vùng tạm trước khi người dùng xác nhận lưu vào thư mục đích.
- **FR-009**: Hệ thống MUST cho phép người dùng mở/xem PDF tạm và tên đầu ra trước khi xác nhận lưu.
- **FR-010**: Hệ thống MUST dùng thiết lập trang/in hiện có của tài liệu Office làm mặc định, MUST không thay đổi tệp nguồn, và MUST không xuất slide ẩn hoặc trang ghi chú PowerPoint theo mặc định.
- **FR-011**: Hệ thống MUST hiển thị tiến độ và tổng kết gồm số tệp nguồn, thành công, lỗi, bỏ qua, tên đầu ra và lý do lỗi.
- **FR-012**: Hệ thống MUST chuyển đổi/OCR trên máy người dùng và MUST xóa dữ liệu tạm sau khi lưu hoặc hủy lô. Chỉ chức năng OpenAI API tùy chọn mới được phép gửi đoạn văn bản giới hạn sau khi người dùng đồng ý rõ ràng.
- **FR-013**: Hệ thống MUST hiển thị thông báo và hướng dẫn bằng tiếng Việt phổ thông.
- **FR-014**: Hệ thống MUST giữ hình ảnh/trang gốc của PDF scan, thêm lớp chữ OCR để tìm kiếm/chọn/sao chép, và MUST không chuyển nội dung thành Word/Excel có thể chỉnh sửa.
- **FR-015**: Hệ thống MUST cho chọn ngôn ngữ OCR tiếng Việt, tiếng Anh hoặc kết hợp; ngôn ngữ mặc định là tiếng Việt. Nếu gói ngôn ngữ thiếu hoặc OCR không nhận diện được chữ, hệ thống MUST báo rõ và cho xem lại PDF.
- **FR-016**: Hệ thống MUST dùng OCR chạy cục bộ; không tải tệp PDF/ảnh gốc lên dịch vụ bên ngoài. Chia sẻ đoạn chữ với AI cloud chỉ được phép theo FR-019.
- **FR-017**: Hệ thống MAY cung cấp gợi ý phân loại, lọc và đặt tên bằng Ollama cục bộ hoặc OpenAI API; mặc định không chạy cho tới khi người dùng chủ động yêu cầu.
- **FR-018**: Gợi ý AI MUST chỉ dựa trên đoạn trích PDF có giới hạn, MUST không tự bỏ chọn/xóa/lưu tệp, và MUST để người dùng duyệt trước khi áp dụng hoặc lưu.
- **FR-019**: OpenAI API MUST bị tắt nếu thiếu API key hoặc người dùng chưa đồng ý gửi đoạn trích. Yêu cầu MUST dùng HTTPS, Responses API, đầu ra JSON theo schema và `store=false`; MUST NOT tải nguyên tệp PDF lên API.
- **FR-020**: Hệ thống MUST cung cấp CLI cho chuyển đổi lô, liệt kê model Ollama và phân loại PDF; lệnh cloud MUST yêu cầu cờ xác nhận `--allow-cloud`.
- **FR-021**: Hệ thống MUST cung cấp điểm khởi chạy desktop trên Windows, mở cửa sổ riêng bằng WebView2 và chỉ bind máy chủ giao diện trên loopback.

### Key Entities

- **Tệp nguồn**: Một tài liệu Office, PDF scan hoặc ảnh do người dùng chọn, có tên, loại, vị trí và trạng thái kiểm tra.
- **Lô chuyển đổi**: Một lần xử lý nhiều tệp, có thư mục đích, tiến độ và kết quả.
- **PDF tạm**: Kết quả được tạo trong vùng tạm để người dùng xem trước trước khi lưu chính thức.
- **PDF đầu ra**: Tệp đã được xác nhận và lưu, gắn với tệp nguồn và tên cuối cùng.
- **Vấn đề chuyển đổi/OCR**: Một lỗi hoặc cảnh báo theo tệp, như định dạng không hỗ trợ, mật khẩu, tên trùng, thiếu gói ngôn ngữ hoặc lỗi khi tạo lớp chữ.
- **Gợi ý AI**: Nhãn nhóm, đề xuất giữ/bỏ qua/xem lại, lý do và tên PDF gợi ý; không thay đổi trạng thái lưu nếu người dùng chưa thao tác.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Trên bộ chấp nhận gồm tối đa 20 tệp Office, PDF scan và ảnh scan, mỗi tệp hợp lệ tạo đúng một PDF mở được; không tệp nguồn nào bị thay đổi.
- **SC-002**: Trên bộ có tệp lỗi và tệp tên trùng được chuẩn bị trước, mọi lỗi và xung đột đều được báo trước khi lưu; không có tệp nào bị ghi đè âm thầm.
- **SC-003**: Trong thử nghiệm với 5 nhân viên văn phòng mới, ít nhất 4 người hoàn tất chọn tệp, kiểm tra tên, xem trước và lưu lô mà không cần người hướng dẫn thao tác thay.
- **SC-004**: Với cùng một người dùng và cùng 20 tài liệu Office, thời gian từ lúc chọn tệp tới khi hoàn tất kiểm tra và lưu giảm ít nhất 40% so với việc lưu từng tệp thủ công; thời gian xem lại PDF được tính vào cả hai cách. Thời gian OCR scan được đo riêng.
- **SC-005**: Trong bộ tài liệu đại diện, không có lỗi chuyển đổi/OCR nhìn thấy được bị báo thành thành công mà không có cơ hội xem trước trước khi lưu.
- **SC-006**: Với PDF scan và ảnh có chữ in rõ, đầu ra giữ được hình ảnh nguồn và cho phép tìm kiếm/chọn phần chữ đã nhận diện; độ chính xác được kiểm tra thủ công theo ngôn ngữ đã chọn.
- **SC-007**: Lô vượt 20 tệp hoặc 500 MB bị chặn trước khi chuyển nội dung vào vùng staging; giao diện nêu giới hạn và cách chia lô.
- **SC-008**: Cửa sổ desktop chỉ mở dịch vụ giao diện trên `127.0.0.1` và dừng dịch vụ khi đóng cửa sổ.
- **SC-009**: CLI xử lý tối đa 20 tệp, không ghi đè âm thầm và trả mã thoát khác 0 khi có tệp lỗi.
- **SC-010**: Chưa có API key hoặc thiếu xác nhận cloud thì không có request OpenAI; request hợp lệ chỉ chứa tối đa 12.000 ký tự trích từ PDF.

## Assumptions

- Người dùng đầu tiên là nhân viên văn phòng dùng Windows và xử lý tệp Office theo lô.
- Mỗi lô có tối đa 20 tệp trong bản MVP.
- MVP nhận .docx, .xlsx, .pptx, PDF và các định dạng ảnh phổ biến; định dạng Office cũ, macro-enabled, GIF/HEIC và TIFF nhiều khung chưa được hỗ trợ.
- OCR mặc định dùng gói ngôn ngữ tiếng Việt; người dùng có thể chọn tiếng Anh hoặc tiếng Việt + tiếng Anh nếu các gói đó đã cài.
- Tên đầu ra mặc định lấy từ tên gốc; nếu trùng, hệ thống tự thêm hậu tố và cho xem trước trước khi lưu.
- Tệp Excel và PowerPoint sử dụng thiết lập trang/in hiện có; người dùng kiểm tra PDF trước khi lưu.
- Ngưỡng giảm thời gian 40% và bộ 20 tài liệu là mục tiêu ban đầu, cần đo lại trong pilot.
- Chuyển đổi và OCR chỉ chạy cục bộ; không có máy chủ OfficeFlow nhận tài liệu.
- AI là tùy chọn. Ollama chạy cục bộ; OpenAI API yêu cầu API key, xác nhận gửi dữ liệu và có thể phát sinh phí. Tắt hoặc thiếu AI không ảnh hưởng chuyển đổi/OCR.

### Out of Scope

- OCR PDF/ảnh sang Word/Excel có thể chỉnh sửa.
- Ghép nhiều ảnh thành một PDF nhiều trang; mỗi ảnh được xử lý thành một PDF riêng.
- Nhận dạng chữ viết tay; độ chính xác OCR không được bảo đảm và cần xem lại PDF.
- Chuyển Word thành slide PowerPoint hoặc tái cấu trúc nội dung thành bài trình chiếu.
- Trích bảng trong Word thành Excel.
- Ghép nhiều tệp nguồn thành một PDF, tách PDF, ký số hoặc gửi email.
- Sửa nội dung tài liệu, dàn trang lại, hoặc tự sửa lỗi phông chữ.
- Chạy chuyển đổi trên máy chủ hoặc xử lý đồng thời nhiều người dùng.
- Đồng bộ tài liệu hoặc cấu hình API key lên dịch vụ OfficeFlow.

### Dependencies

- Cần LibreOffice cục bộ để chuyển Office sang PDF. Microsoft Office đã cài không được prototype tự điều khiển; lựa chọn tự động hóa COM bị loại vì có thể treo hoặc chờ hộp thoại trong tiến trình nền. OCR PDF/ảnh cần OCRmyPDF, Tesseract và gói ngôn ngữ được cài cục bộ; không cần LibreOffice nếu lô chỉ gồm scan.
- Cần có một bộ tài liệu mẫu đại diện cho Word, Excel và PowerPoint, bao gồm thiết lập in, dấu tiếng Việt và các trường hợp lỗi.
- Trước khi dùng tài liệu công việc thật, cần xác nhận chính sách xử lý dữ liệu và quyền sử dụng trên thiết bị của người dùng.

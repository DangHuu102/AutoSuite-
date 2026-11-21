"""Vietnamese labels and messages shown by the user interface."""

from .models import BatchState, IssueCode, OutputStatus, SourceStatus

APP_TITLE = "AutoSuite · Chuyển tài liệu sang PDF"
APP_DESCRIPTION = (
    "Chuyển Word, Excel, PowerPoint và tài liệu scan sang PDF theo lô, có OCR và bước duyệt trước khi lưu."
)

BATCH_STATE_LABELS = {
    BatchState.SELECTED: "Đã chọn tệp",
    BatchState.PREFLIGHT: "Đang chờ chuyển đổi",
    BatchState.CONVERTING: "Đang chuyển đổi",
    BatchState.REVIEW: "Đang chờ bạn xem lại",
    BatchState.COMMITTED: "Đã hoàn tất",
    BatchState.CANCELLED: "Đã hủy",
    BatchState.FAILED: "Có tệp lỗi",
}

SOURCE_STATUS_LABELS = {
    SourceStatus.SELECTED: "Đã chọn",
    SourceStatus.VALID: "Sẵn sàng",
    SourceStatus.CONVERTING: "Đang chuyển",
    SourceStatus.CONVERTED: "Đã tạo PDF",
    SourceStatus.FAILED: "Lỗi",
    SourceStatus.SKIPPED: "Bỏ qua",
}

OUTPUT_STATUS_LABELS = {
    OutputStatus.STAGED: "Đang chờ xem lại",
    OutputStatus.PREVIEWED: "Đã xem trước",
    OutputStatus.COMMITTED: "Đã lưu",
    OutputStatus.DISCARDED: "Đã bỏ qua",
    OutputStatus.FAILED: "Không lưu được",
}

ISSUE_MESSAGES = {
    IssueCode.UNSUPPORTED_TYPE: (
        "Định dạng này chưa được hỗ trợ. Chọn Office .docx/.xlsx/.pptx, PDF hoặc ảnh "
        ".png/.jpg/.jpeg/.tif/.tiff/.bmp."
    ),
    IssueCode.UNREADABLE: "Không đọc được tệp. Tệp có thể bị hỏng hoặc không đúng định dạng.",
    IssueCode.PASSWORD_PROTECTED: "Tệp có thể được mã hóa bằng mật khẩu; hãy mở và lưu bản không khóa.",
    IssueCode.CONVERSION_FAILED: "Không tạo được PDF. Hãy thử mở tệp trong ứng dụng Office hoặc LibreOffice.",
    IssueCode.OCR_FAILED: "Không tạo được lớp chữ OCR. Kiểm tra ngôn ngữ OCR đã cài và chất lượng tệp scan.",
    IssueCode.NAME_CONFLICT: "Tên PDF bị trùng. Đã đề xuất tên khác để tránh ghi đè.",
    IssueCode.DESTINATION_ERROR: "Không thể lưu vào thư mục đích. Kiểm tra quyền truy cập và dung lượng trống.",
    IssueCode.PREVIEW_WARNING: "Không đọc được thông tin trang của PDF; hãy kiểm tra bản xem trước.",
}

LIBREOFFICE_MISSING = (
    "Bản OfficeFlow hiện dùng LibreOffice làm bộ máy dàn trang và xuất PDF tại máy cho DOCX/XLSX/PPTX. "
    "Microsoft Office đã cài vẫn không được app tự gọi. Cài LibreOffice Desktop bằng "
    "`winget install -e --id TheDocumentFoundation.LibreOffice`; chỉ xử lý PDF/ảnh scan thì không cần LibreOffice."
)

"""Local OCR adapter for scanned PDFs and single-image files."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .converter import ConversionError, ConversionResult
from .models import IssueCode
from .validation import IMAGE_EXTENSIONS

SUPPORTED_OCR_LANGUAGES = {"vie", "eng", "vie+eng"}
DEFAULT_OCR_TIMEOUT_SECONDS = 600


def find_ocrmypdf() -> str | None:
    configured = os.environ.get("OFFICEFLOW_OCRMYPDF")
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    found = shutil.which("ocrmypdf") or shutil.which("ocrmypdf.exe")
    if found:
        return found
    sibling = Path(sys.executable).with_name("ocrmypdf.exe")
    if sibling.is_file():
        return str(sibling)
    return None


class OCRProcessor:
    """Create searchable PDFs locally using OCRmyPDF and Tesseract."""

    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    ) -> None:
        self.executable = executable or find_ocrmypdf()
        self.timeout_seconds = timeout_seconds
        if not self.executable:
            raise FileNotFoundError("Không tìm thấy OCRmyPDF trong môi trường Python hiện tại.")

    def process(self, source_path: Path, output_path: Path, language: str = "vie") -> ConversionResult:
        if language not in SUPPORTED_OCR_LANGUAGES:
            raise ValueError("Ngôn ngữ OCR không được hỗ trợ.")
        extension = source_path.suffix.casefold()
        if extension != ".pdf" and extension not in IMAGE_EXTENSIONS:
            raise ConversionError("OCR chỉ nhận PDF hoặc ảnh scan.", IssueCode.UNSUPPORTED_TYPE)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        input_path = source_path
        if extension in IMAGE_EXTENSIONS:
            # Normalize supported single images to PNG in staging. This keeps OCRmyPDF's
            # single-image path consistent without ever rewriting the user's source.
            input_path = output_path.parent / "ocr-input.png"
            try:
                with Image.open(source_path) as source_image:
                    if "A" in source_image.getbands() or "transparency" in source_image.info:
                        rgba = source_image.convert("RGBA")
                        flattened = Image.new("RGB", rgba.size, "white")
                        flattened.paste(rgba, mask=rgba.getchannel("A"))
                        normalized_image = flattened
                    elif source_image.mode in {"1", "L", "RGB"}:
                        normalized_image = source_image
                    else:
                        normalized_image = source_image.convert("RGB")
                    normalized_image.save(input_path, format="PNG", dpi=(300, 300))
            except OSError as exc:
                raise ConversionError("Không đọc được ảnh scan.", IssueCode.UNREADABLE) from exc

        args = [
            self.executable,
            "--output-type",
            "pdf",
            "--skip-text",
            "--jobs",
            "1",
            "-l",
            language,
        ]
        if extension in IMAGE_EXTENSIONS:
            args.extend(["--image-dpi", "300"])
        args.extend([str(input_path), str(output_path)])

        try:
            process = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError(
                f"OCR vượt quá {self.timeout_seconds} giây; hãy thử xử lý tệp ít trang hơn.",
                IssueCode.OCR_FAILED,
            ) from exc
        except OSError as exc:
            raise ConversionError(
                "Không khởi chạy được OCRmyPDF. Kiểm tra cài đặt OCRmyPDF/Tesseract.",
                IssueCode.OCR_FAILED,
            ) from exc

        if process.returncode != 0 or not output_path.is_file():
            combined = f"{process.stderr}\n{process.stdout}".casefold()
            if "failed loading language" in combined or "traineddata" in combined:
                message = (
                    f"Thiếu gói ngôn ngữ OCR '{language}'. Cài gói Tesseract tương ứng rồi thử lại."
                )
            elif "encrypted" in combined or "password" in combined:
                message = "PDF được bảo vệ bằng mật khẩu; hãy lưu một bản PDF không khóa rồi thử lại."
                raise ConversionError(message, IssueCode.PASSWORD_PROTECTED)
            elif "digital signature" in combined or "signed pdf" in combined:
                message = "PDF có chữ ký số. OCR không thể giữ hiệu lực chữ ký; hãy dùng bản chưa ký."
                raise ConversionError(message, IssueCode.OCR_FAILED)
            else:
                message = (
                    "OCR không hoàn tất. Kiểm tra định dạng, ngôn ngữ Tesseract đã cài, "
                    "quyền truy cập và chất lượng scan."
                )
            raise ConversionError(message, IssueCode.OCR_FAILED)

        try:
            with output_path.open("rb") as pdf_file:
                if pdf_file.read(5) != b"%PDF-":
                    raise ConversionError("OCR tạo kết quả không phải PDF.", IssueCode.OCR_FAILED)
            reader = PdfReader(str(output_path), strict=False)
            if reader.is_encrypted:
                raise ConversionError("PDF kết quả đang bị khóa.", IssueCode.OCR_FAILED)
            page_count = len(reader.pages)
            if page_count < 1:
                raise ConversionError("PDF kết quả không có trang.", IssueCode.OCR_FAILED)
            text_length = sum(len(page.extract_text() or "") for page in reader.pages)
        except (OSError, PdfReadError, ValueError, TypeError) as exc:
            raise ConversionError("PDF tạo từ OCR không đọc được hoặc bị hỏng.", IssueCode.OCR_FAILED) from exc

        return ConversionResult(
            pdf_path=output_path,
            page_count=page_count,
            searchable_text_chars=text_length,
        )

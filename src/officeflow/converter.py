"""LibreOffice headless conversion with isolated per-file profiles."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .models import IssueCode
from .staging import _rmtree_force

_FILTERS = {
    ".docx": ("writer_pdf_Export", {}),
    ".xlsx": ("calc_pdf_Export", {}),
    ".pptx": (
        "impress_pdf_Export",
        {
            "ExportHiddenSlides": {"type": "boolean", "value": "false"},
            "ExportNotesPages": {"type": "boolean", "value": "false"},
        },
    ),
}
DEFAULT_TIMEOUT_SECONDS = 180


class ConversionError(RuntimeError):
    def __init__(self, message_vi: str, issue_code: IssueCode = IssueCode.CONVERSION_FAILED):
        super().__init__(message_vi)
        self.issue_code = issue_code
        self.message_vi = message_vi


@dataclass(slots=True)
class ConversionResult:
    pdf_path: Path
    page_count: int
    searchable_text_chars: int | None = None


def find_libreoffice() -> str | None:
    """Find soffice from PATH or common Windows install folders."""
    configured = os.environ.get("OFFICEFLOW_SOFFICE")
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())

    for executable in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(executable)
        if found:
            return found

    program_roots = {
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
    }
    program_roots.discard(None)
    for root in program_roots:
        candidate = Path(root) / "LibreOffice" / "program" / "soffice.exe"
        if candidate.is_file():
            return str(candidate)
    return None


class LibreOfficeConverter:
    def __init__(self, executable: str | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.executable = executable or find_libreoffice()
        self.timeout_seconds = timeout_seconds
        if not self.executable:
            raise FileNotFoundError("Không tìm thấy LibreOffice (soffice).")

    def convert_to_pdf(self, source_path: Path, output_dir: Path) -> ConversionResult:
        extension = source_path.suffix.casefold()
        if extension not in _FILTERS:
            raise ConversionError("Định dạng này chưa được hỗ trợ.", IssueCode.UNSUPPORTED_TYPE)

        filter_name, filter_options = _FILTERS[extension]
        filter_argument = f"pdf:{filter_name}"
        if filter_options:
            filter_argument += f":{json.dumps(filter_options, separators=(',', ':'))}"

        output_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = Path(tempfile.mkdtemp(prefix="lo-p-"))
        expected_pdf = output_dir / f"{source_path.stem}.pdf"
        try:
            args = [
                self.executable,
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--norestore",
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--convert-to",
                filter_argument,
                "--outdir",
                str(output_dir),
                str(source_path),
            ]
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
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise ConversionError(
                    f"Quá thời gian chờ {self.timeout_seconds} giây; hãy thử chuyển riêng tệp này."
                ) from exc
            except OSError as exc:
                raise ConversionError("Không khởi chạy được LibreOffice để chuyển tệp.") from exc

            if process.returncode != 0 or not expected_pdf.is_file():
                details = f"{process.stderr}\n{process.stdout}".casefold()
                if "password" in details or "encrypted" in details:
                    raise ConversionError(
                        "LibreOffice không mở được tệp; tệp có thể được bảo vệ bằng mật khẩu.",
                        IssueCode.PASSWORD_PROTECTED,
                    )
                raise ConversionError(
                    "LibreOffice không tạo được PDF. Hãy kiểm tra tệp nguồn, quyền truy cập "
                    "và thiết lập in."
                )

            try:
                with expected_pdf.open("rb") as pdf_file:
                    if pdf_file.read(5) != b"%PDF-":
                        raise ConversionError("Kết quả không phải là tệp PDF hợp lệ.")
                reader = PdfReader(str(expected_pdf), strict=False)
                if reader.is_encrypted:
                    raise ConversionError("PDF tạo ra đang bị khóa và không thể xem trước.")
                page_count = len(reader.pages)
                if page_count < 1:
                    raise ConversionError("PDF tạo ra không có trang để xem.")
            except (OSError, PdfReadError, ValueError) as exc:
                raise ConversionError("PDF tạo ra không đọc được hoặc bị hỏng.") from exc

            return ConversionResult(pdf_path=expected_pdf, page_count=page_count)
        finally:
            _rmtree_force(profile_dir)

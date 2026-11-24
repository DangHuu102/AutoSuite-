"""Preflight checks for explicitly selected Office files."""

from __future__ import annotations

import zipfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .messages_vi import ISSUE_MESSAGES
from .models import ConversionIssue, IssueCode, SourceFile, SourceStatus

OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
OCR_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
SUPPORTED_EXTENSIONS = OFFICE_EXTENSIONS | OCR_EXTENSIONS
REJECTED_EXTENSIONS = {".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm", ".gif", ".heic"}
MAX_FILES_PER_BATCH = 20
MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024
MAX_BATCH_BYTES = 500 * 1024 * 1024
_CFB_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_OOXML_MAIN_PARTS = {
    ".docx": "word/document.xml",
    ".xlsx": "xl/workbook.xml",
    ".pptx": "ppt/presentation.xml",
}


def _issue(code: IssueCode, source_id: str, message: str | None = None) -> ConversionIssue:
    return ConversionIssue(
        issue_code=code,
        severity="error",
        message_vi=message or ISSUE_MESSAGES[code],
        source_id=source_id,
        blocks_commit=True,
    )


def validate_source(source: SourceFile) -> list[ConversionIssue]:
    """Check extension and basic OOXML readability without changing the source."""
    extension = source.extension.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        return [_issue(IssueCode.UNSUPPORTED_TYPE, source.source_id)]

    path = source.source_location
    if path is None or not path.is_file():
        return [_issue(IssueCode.UNREADABLE, source.source_id)]

    try:
        if path.stat().st_size <= 0:
            return [_issue(IssueCode.UNREADABLE, source.source_id)]
        with path.open("rb") as source_stream:
            signature = source_stream.read(8)
        if extension == ".pdf":
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted:
                return [_issue(IssueCode.PASSWORD_PROTECTED, source.source_id)]
            if not reader.pages:
                return [_issue(IssueCode.UNREADABLE, source.source_id)]
            return []
        if extension in IMAGE_EXTENSIONS:
            with Image.open(path) as image:
                if extension in {".tif", ".tiff"} and getattr(image, "n_frames", 1) > 1:
                    return [
                        _issue(
                            IssueCode.UNSUPPORTED_TYPE,
                            source.source_id,
                            "MVP chưa nhận TIFF nhiều khung. Hãy lưu từng ảnh hoặc gộp trang thành PDF.",
                        )
                    ]
                image.verify()
            return []
        if signature == _CFB_SIGNATURE:
            return [
                _issue(
                    IssueCode.PASSWORD_PROTECTED,
                    source.source_id,
                    "Tệp có dạng vùng chứa Office được mã hóa hoặc không phải OOXML hợp lệ. "
                    "Hãy mở tệp và lưu một bản .docx, .xlsx hoặc .pptx không khóa.",
                )
            ]

        with zipfile.ZipFile(path) as package:
            members = package.infolist()
            names = {item.filename for item in members}
            required = {"[Content_Types].xml", "_rels/.rels", _OOXML_MAIN_PARTS[extension]}
            if not required.issubset(names):
                return [_issue(IssueCode.UNREADABLE, source.source_id)]
            if any(item.flag_bits & 0x1 for item in members):
                return [_issue(IssueCode.PASSWORD_PROTECTED, source.source_id)]
    except (
        OSError,
        zipfile.BadZipFile,
        PdfReadError,
        Image.DecompressionBombError,
        RuntimeError,
        ValueError,
        TypeError,
    ):
        return [_issue(IssueCode.UNREADABLE, source.source_id)]

    return []


def apply_preflight(source: SourceFile) -> SourceFile:
    """Attach preflight issues and set the source's initial status."""
    source.issues = validate_source(source)
    if not source.issues:
        source.status = SourceStatus.VALID
    elif source.issues[0].issue_code is IssueCode.UNSUPPORTED_TYPE:
        source.status = SourceStatus.SKIPPED
    else:
        source.status = SourceStatus.FAILED
    return source

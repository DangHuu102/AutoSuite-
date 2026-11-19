"""Batch preflight, conversion, commit, and retry orchestration."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

from .converter import ConversionError, LibreOfficeConverter
from .messages_vi import ISSUE_MESSAGES
from .models import (
    BatchJob,
    BatchState,
    ConversionIssue,
    IssueCode,
    OutputPdf,
    OutputStatus,
    SourceFile,
    SourceStatus,
)
from .naming import propose_output_names
from .ocr import OCRProcessor
from .staging import (
    cleanup_batch_staging,
    commit_staged_pdf,
    create_batch_staging,
    source_output_dir,
    store_source_bytes,
)
from .validation import (
    IMAGE_EXTENSIONS,
    MAX_BATCH_BYTES,
    MAX_FILES_PER_BATCH,
    OFFICE_EXTENSIONS,
    apply_preflight,
)

ProgressCallback = Callable[[int, int, SourceFile], None]


def _upload_bytes(upload: Any) -> bytes:
    if hasattr(upload, "getvalue"):
        return bytes(upload.getvalue())
    if hasattr(upload, "read"):
        return bytes(upload.read())
    raise TypeError("Không đọc được tệp đã chọn.")


def _upload_name(upload: Any) -> str:
    value = str(getattr(upload, "name", "") or "tai-lieu")
    return value.replace("\\", "/").split("/")[-1]


def _upload_size(upload: Any) -> int:
    size = getattr(upload, "size", None)
    if isinstance(size, int) and size >= 0:
        return size
    getbuffer = getattr(upload, "getbuffer", None)
    if callable(getbuffer):
        return getbuffer().nbytes
    if hasattr(upload, "getvalue"):
        return len(upload.getvalue())
    raise ValueError("Không xác định được dung lượng của một tệp đã chọn.")


def create_batch_job(
    uploads: Sequence[Any], destination: Path, ocr_language: str = "vie"
) -> BatchJob:
    """Copy selected uploads into isolated staging and run preflight checks."""
    if len(uploads) > MAX_FILES_PER_BATCH:
        raise ValueError(f"Mỗi lô nhận tối đa {MAX_FILES_PER_BATCH} tệp.")
    if not uploads:
        raise ValueError("Hãy chọn ít nhất một tệp.")
    total_bytes = sum(_upload_size(upload) for upload in uploads)
    if total_bytes > MAX_BATCH_BYTES:
        raise ValueError("Tổng dung lượng mỗi lô tối đa 500 MB. Hãy chia thành nhiều lô nhỏ hơn.")

    destination = destination.expanduser().resolve(strict=True)
    if not destination.is_dir():
        raise ValueError("Hãy chọn một thư mục đích đang tồn tại.")

    job = BatchJob(destination=destination, ocr_language=ocr_language)
    job.staging_dir = create_batch_staging(job.batch_id)
    job.state = BatchState.PREFLIGHT

    for upload in uploads:
        original_name = _upload_name(upload)
        extension = Path(original_name).suffix.casefold()
        source_id = uuid4().hex
        source = SourceFile(
            source_id=source_id,
            original_name=original_name,
            extension=extension,
            byte_size=0,
        )
        try:
            data = _upload_bytes(upload)
            source.byte_size = len(data)
            source.source_location = store_source_bytes(
                job.staging_dir, source_id, original_name, data
            )
            del data
            apply_preflight(source)
        except (OSError, TypeError, ValueError) as exc:
            source.status = SourceStatus.FAILED
            source.issues.append(
                ConversionIssue(
                    issue_code=IssueCode.UNREADABLE,
                    severity="error",
                    message_vi=ISSUE_MESSAGES[IssueCode.UNREADABLE],
                    source_id=source_id,
                )
            )
        job.sources.append(source)

    valid_sources = [item for item in job.sources if item.status is SourceStatus.VALID]
    names = propose_output_names([item.original_name for item in valid_sources], destination)
    for source, proposed_name in zip(valid_sources, names, strict=True):
        source.proposed_output_name = proposed_name
    return job


def convert_batch(
    job: BatchJob,
    converter: LibreOfficeConverter | None,
    ocr_processor: OCRProcessor | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BatchJob:
    """Convert each valid input independently and leave PDFs in staging."""
    if job.staging_dir is None:
        raise RuntimeError("Không còn vùng tạm cho lô này.")
    job.state = BatchState.CONVERTING
    sources = [item for item in job.sources if item.status is SourceStatus.VALID]
    total = len(sources)

    for completed, source in enumerate(sources, start=1):
        job.current_source_id = source.source_id
        source.status = SourceStatus.CONVERTING
        try:
            if source.source_location is None:
                raise ConversionError("Không tìm thấy tệp nguồn trong vùng tạm.")
            output_dir = source_output_dir(job.staging_dir, source.source_id)
            if source.extension in OFFICE_EXTENSIONS:
                if converter is None:
                    raise ConversionError("Không tìm thấy LibreOffice để xử lý tệp Office.")
                result = converter.convert_to_pdf(source.source_location, output_dir)
            elif source.extension == ".pdf" or source.extension in IMAGE_EXTENSIONS:
                if ocr_processor is None:
                    raise ConversionError(
                        "Không tìm thấy OCRmyPDF. Hãy cài OCRmyPDF và Tesseract.",
                        IssueCode.OCR_FAILED,
                    )
                ocr_path = output_dir / "result.pdf"
                result = ocr_processor.process(source.source_location, ocr_path, job.ocr_language)
            else:
                raise ConversionError("Định dạng này chưa được hỗ trợ.", IssueCode.UNSUPPORTED_TYPE)
            output = OutputPdf(
                output_id=uuid4().hex,
                source_id=source.source_id,
                proposed_name=source.proposed_output_name,
                final_name=source.proposed_output_name,
                staging_path=result.pdf_path,
                page_count=result.page_count,
                searchable_text=(
                    result.searchable_text_chars > 0
                    if result.searchable_text_chars is not None
                    else None
                ),
                status=OutputStatus.STAGED,
            )
            if result.searchable_text_chars == 0:
                output.issues.append(
                    ConversionIssue(
                        issue_code=IssueCode.PREVIEW_WARNING,
                        severity="warning",
                        message_vi="Không phát hiện được lớp chữ tìm kiếm trong PDF. Kiểm tra ngôn ngữ "
                        "OCR và chất lượng ảnh trước khi lưu.",
                        source_id=source.source_id,
                        blocks_commit=False,
                    )
                )
            job.outputs.append(output)
            source.status = SourceStatus.CONVERTED
        except ConversionError as exc:
            source.status = SourceStatus.FAILED
            source.issues.append(
                ConversionIssue(
                    issue_code=exc.issue_code,
                    severity="error",
                    message_vi=exc.message_vi,
                    source_id=source.source_id,
                )
            )
        except OSError:
            source.status = SourceStatus.FAILED
            source.issues.append(
                ConversionIssue(
                    issue_code=IssueCode.CONVERSION_FAILED,
                    severity="error",
                    message_vi=ISSUE_MESSAGES[IssueCode.CONVERSION_FAILED],
                    source_id=source.source_id,
                )
            )
        except Exception:
            # A parser/OCR library may raise a format-specific exception outside the
            # adapters' documented errors. Keep the rest of the batch moving.
            source.status = SourceStatus.FAILED
            source.issues.append(
                ConversionIssue(
                    issue_code=IssueCode.CONVERSION_FAILED,
                    severity="error",
                    message_vi=ISSUE_MESSAGES[IssueCode.CONVERSION_FAILED],
                    source_id=source.source_id,
                )
            )
        if progress_callback:
            progress_callback(completed, total, source)

    job.current_source_id = None
    job.state = BatchState.REVIEW
    return job


def commit_batch(
    job: BatchJob,
    selected_output_ids: set[str],
    final_names_by_output_id: dict[str, str],
) -> BatchJob:
    """Publish only checked PDFs and then remove the batch's temporary files."""
    for output in job.outputs:
        if output.output_id not in selected_output_ids:
            output.status = OutputStatus.DISCARDED
            continue
        try:
            commit_staged_pdf(
                output,
                job.destination,
                final_names_by_output_id.get(output.output_id, output.final_name),
            )
        except FileExistsError:
            output.status = OutputStatus.FAILED
            output.issues.append(
                ConversionIssue(
                    issue_code=IssueCode.NAME_CONFLICT,
                    severity="error",
                    message_vi="Tên vừa bị một tệp khác sử dụng. Không có tệp nào bị ghi đè; "
                    "hãy tạo lô mới và chọn tên khác.",
                    source_id=output.source_id,
                )
            )
        except (OSError, ValueError, RuntimeError):
            output.status = OutputStatus.FAILED
            output.issues.append(
                ConversionIssue(
                    issue_code=IssueCode.DESTINATION_ERROR,
                    severity="error",
                    message_vi=ISSUE_MESSAGES[IssueCode.DESTINATION_ERROR],
                    source_id=output.source_id,
                )
            )

    cleanup_batch_staging(job.staging_dir)
    job.staging_dir = None
    if job.succeeded_count:
        job.state = BatchState.COMMITTED
    elif job.failed_count:
        job.state = BatchState.FAILED
    else:
        job.state = BatchState.CANCELLED
    return job


def cancel_batch(job: BatchJob) -> BatchJob:
    """Discard staged work and leave originals and destination files untouched."""
    for output in job.outputs:
        if output.status in {OutputStatus.STAGED, OutputStatus.PREVIEWED}:
            output.status = OutputStatus.DISCARDED
    for source in job.sources:
        if source.status in {SourceStatus.SELECTED, SourceStatus.VALID, SourceStatus.CONVERTED}:
            source.status = SourceStatus.SKIPPED
    cleanup_batch_staging(job.staging_dir)
    job.staging_dir = None
    job.state = BatchState.CANCELLED
    return job


def create_retry_batch(
    previous_job: BatchJob, uploads: Sequence[Any], destination: Path
) -> BatchJob:
    """Start a fresh batch from reselected files corresponding to failed sources."""
    if not uploads:
        raise ValueError("Hãy chọn lại ít nhất một tệp lỗi.")
    failed_source_ids = {
        source.source_id for source in previous_job.sources if source.status is SourceStatus.FAILED
    }
    failed_source_ids.update(
        output.source_id for output in previous_job.outputs if output.status is OutputStatus.FAILED
    )
    expected = Counter(
        source.original_name.casefold()
        for source in previous_job.sources
        if source.source_id in failed_source_ids
    )
    received = Counter(_upload_name(upload).casefold() for upload in uploads)
    if any(name not in expected or count > expected[name] for name, count in received.items()):
        raise ValueError("Chỉ chọn lại các tệp đang có trạng thái lỗi trong lô trước.")
    return create_batch_job(uploads, destination, previous_job.ocr_language)

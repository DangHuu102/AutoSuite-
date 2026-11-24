"""Batch preflight, conversion, commit, and retry orchestration."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

from pypdf import PdfReader, PdfWriter

from .converter import ConversionError, ConversionResult, LibreOfficeConverter
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
from .naming import (
    normalize_pdf_name,
    propose_docx_output_names,
    propose_output_names,
    resolve_unique_pdf_names,
)
from .ocr import OCRProcessor, SUPPORTED_OCR_LANGUAGES
from .pdf_to_word import convert_pdf_to_docx
from .staging import (
    STAGING_ROOT,
    cleanup_batch_staging,
    commit_staged_pdf,
    create_batch_staging,
    source_output_dir,
    store_source_bytes,
    store_source_stream,
)
from .validation import (
    IMAGE_EXTENSIONS,
    MAX_BATCH_BYTES,
    MAX_FILES_PER_BATCH,
    MAX_SINGLE_FILE_BYTES,
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
    raw = getattr(upload, "filename", None) or getattr(upload, "name", "") or "tai-lieu"
    return str(raw).replace("\\", "/").split("/")[-1]


def _upload_size_hint(upload: Any) -> int | None:
    size = getattr(upload, "size", None)
    if isinstance(size, int) and size >= 0:
        return size
    getbuffer = getattr(upload, "getbuffer", None)
    if callable(getbuffer):
        return int(getbuffer().nbytes)
    return None


def _stage_upload(
    staging_dir: Path,
    source_id: str,
    original_name: str,
    upload: Any,
    *,
    max_bytes: int,
) -> tuple[Path, int]:
    """Stream or write an upload to staging without buffering large files in RAM."""
    local_path = getattr(upload, "path", None)
    if isinstance(local_path, Path) and local_path.is_file():
        with local_path.open("rb") as handle:
            return store_source_stream(staging_dir, source_id, original_name, handle, max_bytes)
    file_obj = getattr(upload, "file", None)
    if file_obj is not None and hasattr(file_obj, "read"):
        return store_source_stream(staging_dir, source_id, original_name, file_obj, max_bytes)
    if hasattr(upload, "read"):
        return store_source_stream(staging_dir, source_id, original_name, upload, max_bytes)
    if hasattr(upload, "getvalue"):
        data = bytes(upload.getvalue())
        if len(data) > max_bytes:
            raise OverflowError(f"Tệp '{original_name}' vượt quá giới hạn dung lượng cho phép.")
        target = store_source_bytes(staging_dir, source_id, original_name, data)
        return target, len(data)
    raise TypeError("Không đọc được tệp đã chọn.")


def create_batch_job(
    uploads: Sequence[Any],
    destination: Path | None = None,
    ocr_language: str = "vie",
    *,
    merge_images: bool = False,
    merged_pdf_name: str = "Anh-gop.pdf",
    target_format: str = "pdf",
) -> BatchJob:
    """Copy selected uploads into isolated staging and run preflight checks."""
    if len(uploads) > MAX_FILES_PER_BATCH:
        raise ValueError(f"Mỗi lô nhận tối đa {MAX_FILES_PER_BATCH} tệp.")
    if not uploads:
        raise ValueError("Hãy chọn ít nhất một tệp.")
    if ocr_language not in SUPPORTED_OCR_LANGUAGES:
        raise ValueError("Ngôn ngữ OCR không được hỗ trợ.")
    if target_format not in {"pdf", "docx"}:
        raise ValueError("Định dạng đầu ra không hợp lệ.")
    normalized_merged_name = (
        normalize_pdf_name(merged_pdf_name) if merge_images and target_format == "pdf" else "Anh-gop.pdf"
    )
    known_hints = [_upload_size_hint(upload) for upload in uploads]
    for upload, hint in zip(uploads, known_hints, strict=True):
        if hint is not None and hint > MAX_SINGLE_FILE_BYTES:
            raise ValueError(f"Tệp '{_upload_name(upload)}' vượt quá giới hạn 100 MB mỗi tệp.")
    if sum(h for h in known_hints if h is not None) > MAX_BATCH_BYTES:
        raise ValueError("Tổng dung lượng mỗi lô tối đa 500 MB. Hãy chia thành nhiều lô nhỏ hơn.")

    if destination is not None:
        resolved_dest = destination.expanduser().resolve(strict=True)
        if not resolved_dest.is_dir():
            raise ValueError("Hãy chọn một thư mục đích đang tồn tại.")
    else:
        STAGING_ROOT.mkdir(parents=True, exist_ok=True)
        resolved_dest = STAGING_ROOT

    job = BatchJob(
        destination=resolved_dest,
        ocr_language=ocr_language,
        merge_images=merge_images if target_format == "pdf" else False,
        merged_pdf_name=normalized_merged_name,
        target_format=target_format,
    )
    job.staging_dir = create_batch_staging(job.batch_id)
    job.state = BatchState.PREFLIGHT

    running_total_bytes = 0
    try:
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
            remaining_batch = MAX_BATCH_BYTES - running_total_bytes
            if remaining_batch <= 0:
                raise ValueError(
                    "Tổng dung lượng mỗi lô tối đa 500 MB. Hãy chia thành nhiều lô nhỏ hơn."
                )
            max_allowed = min(MAX_SINGLE_FILE_BYTES, remaining_batch)
            try:
                staged_path, written_bytes = _stage_upload(
                    job.staging_dir,
                    source_id,
                    original_name,
                    upload,
                    max_bytes=max_allowed,
                )
                running_total_bytes += written_bytes
                source.byte_size = written_bytes
                source.source_location = staged_path
                apply_preflight(source)
                if target_format == "docx" and source.status is SourceStatus.VALID and source.extension != ".pdf":
                    source.status = SourceStatus.SKIPPED
                    source.issues.append(
                        ConversionIssue(
                            issue_code=IssueCode.UNSUPPORTED_TYPE,
                            severity="error",
                            message_vi="Chế độ PDF sang Word (.docx) chỉ nhận tệp đầu vào là .pdf.",
                            source_id=source_id,
                        )
                    )
            except OverflowError as exc:
                if remaining_batch < MAX_SINGLE_FILE_BYTES:
                    raise ValueError(
                        "Tổng dung lượng mỗi lô tối đa 500 MB. Hãy chia thành nhiều lô nhỏ hơn."
                    ) from exc
                raise ValueError(
                    f"Tệp '{original_name}' vượt quá giới hạn 100 MB mỗi tệp."
                ) from exc
            except (OSError, TypeError, ValueError):
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
        if target_format == "docx":
            names = propose_docx_output_names(
                [item.original_name for item in valid_sources],
                resolved_dest if destination is not None else None,
            )
            for source, proposed_name in zip(valid_sources, names, strict=True):
                source.proposed_output_name = proposed_name
        elif merge_images:
            non_images = [item for item in valid_sources if item.extension not in IMAGE_EXTENSIONS]
            images = [item for item in valid_sources if item.extension in IMAGE_EXTENSIONS]
            raw_candidates = [
                f"{item.original_name.rsplit('.', 1)[0]}.pdf"
                if "." in item.original_name
                else f"{item.original_name}.pdf"
                for item in non_images
            ]
            if images:
                raw_candidates.append(normalized_merged_name)
            resolved = resolve_unique_pdf_names(raw_candidates, resolved_dest) if raw_candidates else []
            for source, proposed_name in zip(non_images, resolved[: len(non_images)], strict=True):
                source.proposed_output_name = proposed_name
            if images and resolved:
                job.merged_pdf_name = resolved[-1]
                for img in images:
                    img.proposed_output_name = job.merged_pdf_name
        else:
            names = propose_output_names([item.original_name for item in valid_sources], resolved_dest)
            for source, proposed_name in zip(valid_sources, names, strict=True):
                source.proposed_output_name = proposed_name
        return job
    except Exception:
        cleanup_batch_staging(job.staging_dir)
        job.staging_dir = None
        raise


def _append_staged_output(
    job: BatchJob,
    source: SourceFile,
    result: ConversionResult,
    *,
    proposed_name: str | None = None,
    source_ids: list[str] | None = None,
) -> OutputPdf:
    chosen_name = proposed_name or source.proposed_output_name
    output = OutputPdf(
        output_id=uuid4().hex,
        source_id=source.source_id,
        source_ids=list(source_ids or [source.source_id]),
        proposed_name=chosen_name,
        final_name=chosen_name,
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
    return output


def _record_source_exception(source: SourceFile, exc: Exception) -> None:
    source.status = SourceStatus.FAILED
    if isinstance(exc, ConversionError):
        code = exc.issue_code
        msg = exc.message_vi
    else:
        code = IssueCode.CONVERSION_FAILED
        msg = ISSUE_MESSAGES[IssueCode.CONVERSION_FAILED]
    source.issues.append(
        ConversionIssue(
            issue_code=code,
            severity="error",
            message_vi=msg,
            source_id=source.source_id,
        )
    )


def convert_batch(
    job: BatchJob,
    converter: LibreOfficeConverter | None,
    ocr_processor: OCRProcessor | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BatchJob:
    """Convert each valid input independently (or merge images when job.merge_images=True)."""
    if job.staging_dir is None:
        raise RuntimeError("Không còn vùng tạm cho lô này.")
    job.state = BatchState.CONVERTING
    sources = [item for item in job.sources if item.status is SourceStatus.VALID]
    total = len(sources)

    if job.target_format == "docx":
        for completed, source in enumerate(sources, start=1):
            job.current_source_id = source.source_id
            source.status = SourceStatus.CONVERTING
            try:
                if source.source_location is None:
                    raise ConversionError("Không tìm thấy tệp nguồn trong vùng tạm.")
                output_dir = source_output_dir(job.staging_dir, source.source_id)
                word_res = convert_pdf_to_docx(
                    source.source_location,
                    output_dir / "result.docx",
                    ocr_processor=ocr_processor,
                    ocr_language=job.ocr_language,
                )
                output = OutputPdf(
                    output_id=uuid4().hex,
                    source_id=source.source_id,
                    source_ids=[source.source_id],
                    proposed_name=source.proposed_output_name,
                    final_name=source.proposed_output_name,
                    staging_path=word_res.docx_path,
                    page_count=word_res.page_count,
                    searchable_text=True,
                    status=OutputStatus.STAGED,
                    table_count=word_res.table_count,
                    preview_blocks=word_res.preview_blocks,
                )
                job.outputs.append(output)
                source.status = SourceStatus.CONVERTED
            except Exception as exc:
                _record_source_exception(source, exc)
            if progress_callback:
                progress_callback(completed, total, source)
        job.current_source_id = None
        job.state = BatchState.REVIEW
        return job

    if not job.merge_images:
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
                    result = ocr_processor.process(
                        source.source_location, ocr_path, job.ocr_language
                    )
                else:
                    raise ConversionError(
                        "Định dạng này chưa được hỗ trợ.", IssueCode.UNSUPPORTED_TYPE
                    )
                _append_staged_output(job, source, result)
                source.status = SourceStatus.CONVERTED
            except Exception as exc:
                _record_source_exception(source, exc)
            if progress_callback:
                progress_callback(completed, total, source)

        job.current_source_id = None
        job.state = BatchState.REVIEW
        return job

    non_image_sources = [item for item in sources if item.extension not in IMAGE_EXTENSIONS]
    image_sources = [item for item in sources if item.extension in IMAGE_EXTENSIONS]
    completed = 0

    for source in non_image_sources:
        completed += 1
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
            elif source.extension == ".pdf":
                if ocr_processor is None:
                    raise ConversionError(
                        "Không tìm thấy OCRmyPDF. Hãy cài OCRmyPDF và Tesseract.",
                        IssueCode.OCR_FAILED,
                    )
                result = ocr_processor.process(
                    source.source_location, output_dir / "result.pdf", job.ocr_language
                )
            else:
                raise ConversionError("Định dạng này chưa được hỗ trợ.", IssueCode.UNSUPPORTED_TYPE)
            _append_staged_output(job, source, result)
            source.status = SourceStatus.CONVERTED
        except Exception as exc:
            _record_source_exception(source, exc)
        if progress_callback:
            progress_callback(completed, total, source)

    if image_sources:
        if ocr_processor is None:
            for img in image_sources:
                completed += 1
                _record_source_exception(
                    img,
                    ConversionError(
                        "Không tìm thấy OCRmyPDF. Hãy cài OCRmyPDF và Tesseract.",
                        IssueCode.OCR_FAILED,
                    ),
                )
                if progress_callback:
                    progress_callback(completed, total, img)
        else:
            candidates: list[SourceFile] = []
            for img in image_sources:
                if img.source_location is None:
                    completed += 1
                    _record_source_exception(
                        img, ConversionError("Không tìm thấy tệp nguồn trong vùng tạm.")
                    )
                    if progress_callback:
                        progress_callback(completed, total, img)
                else:
                    img.status = SourceStatus.CONVERTING
                    candidates.append(img)

            if candidates:
                merged_dir = source_output_dir(job.staging_dir, "merged-images")
                merged_pdf_path = merged_dir / "result.pdf"
                try:
                    result = ocr_processor.merge_images_to_pdf(
                        [s.source_location for s in candidates if s.source_location is not None],
                        merged_pdf_path,
                        job.ocr_language,
                    )
                    _append_staged_output(
                        job,
                        candidates[0],
                        result,
                        proposed_name=job.merged_pdf_name,
                        source_ids=[s.source_id for s in candidates],
                    )
                    for img in candidates:
                        completed += 1
                        img.status = SourceStatus.CONVERTED
                        if progress_callback:
                            progress_callback(completed, total, img)
                except Exception as exc:
                    if len(candidates) == 1:
                        completed += 1
                        _record_source_exception(candidates[0], exc)
                        if progress_callback:
                            progress_callback(completed, total, candidates[0])
                    else:
                        surviving: list[tuple[SourceFile, ConversionResult]] = []
                        for img in candidates:
                            completed += 1
                            job.current_source_id = img.source_id
                            try:
                                single_dir = source_output_dir(job.staging_dir, img.source_id)
                                single_res = ocr_processor.process(
                                    img.source_location,  # type: ignore[arg-type]
                                    single_dir / "result.pdf",
                                    job.ocr_language,
                                )
                                img.status = SourceStatus.CONVERTED
                                surviving.append((img, single_res))
                            except Exception as single_exc:
                                _record_source_exception(img, single_exc)
                            if progress_callback:
                                progress_callback(completed, total, img)

                        if surviving:
                            writer = PdfWriter()
                            total_chars = 0
                            for _, s_res in surviving:
                                writer.append(str(s_res.pdf_path))
                                total_chars += s_res.searchable_text_chars or 0
                            with merged_pdf_path.open("wb") as out_handle:
                                writer.write(out_handle)
                            reader = PdfReader(str(merged_pdf_path), strict=False)
                            combined_res = ConversionResult(
                                pdf_path=merged_pdf_path,
                                page_count=len(reader.pages),
                                searchable_text_chars=total_chars,
                            )
                            _append_staged_output(
                                job,
                                surviving[0][0],
                                combined_res,
                                proposed_name=job.merged_pdf_name,
                                source_ids=[s.source_id for s, _ in surviving],
                            )

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
    previous_job: BatchJob,
    uploads: Sequence[Any],
    destination: Path,
    ocr_language: str | None = None,
    *,
    merge_images: bool | None = None,
    merged_pdf_name: str | None = None,
) -> BatchJob:
    """Start a fresh batch from reselected files corresponding to failed sources."""
    if not uploads:
        raise ValueError("Hãy chọn lại ít nhất một tệp lỗi.")
    failed_source_ids = {
        source.source_id for source in previous_job.sources if source.status is SourceStatus.FAILED
    }
    for output in previous_job.outputs:
        if output.status is OutputStatus.FAILED:
            failed_source_ids.update(output.related_source_ids)
    expected = Counter(
        source.original_name.casefold()
        for source in previous_job.sources
        if source.source_id in failed_source_ids
    )
    received = Counter(_upload_name(upload).casefold() for upload in uploads)
    if any(name not in expected or count > expected[name] for name, count in received.items()):
        raise ValueError("Chỉ chọn lại các tệp đang có trạng thái lỗi trong lô trước.")
    return create_batch_job(
        uploads,
        destination,
        ocr_language if ocr_language is not None else previous_job.ocr_language,
        merge_images=previous_job.merge_images if merge_images is None else merge_images,
        merged_pdf_name=(
            previous_job.merged_pdf_name if merged_pdf_name is None else merged_pdf_name
        ),
        target_format=previous_job.target_format,
    )

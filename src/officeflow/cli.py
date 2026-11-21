"""Command-line entry points for OfficeFlow conversion and AI suggestions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from officeflow.ai_filter import (
    LocalAIError,
    classify_pdf_batch,
    list_local_models,
    suggest_filter,
    suggest_filter_openai,
)
from officeflow.batch import cancel_batch, commit_batch, convert_batch, create_batch_job
from officeflow.converter import LibreOfficeConverter, find_libreoffice
from officeflow.doctor import collect_doctor_report, format_doctor_json, format_doctor_text
from officeflow.messages_vi import OUTPUT_STATUS_LABELS, SOURCE_STATUS_LABELS
from officeflow.models import OutputStatus, SourceStatus
from officeflow.naming import resolve_unique_docx_names, resolve_unique_pdf_names
from officeflow.ocr import OCRProcessor, find_ocrmypdf
from officeflow.reporting import (
    build_batch_report,
    format_report_csv,
    format_report_json,
    write_report_atomic,
)
from officeflow.staging import cleanup_orphaned_staging_once
from officeflow.validation import MAX_FILES_PER_BATCH


class _LocalUpload:
    """Small upload-compatible wrapper to reuse the preflight and conversion flow."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.name
        self.size = path.stat().st_size

    def getvalue(self) -> bytes:
        return self.path.read_bytes()


def _write_optional_reports(
    job,
    report_json: str | None,
    report_csv: str | None,
) -> None:
    if not report_json and not report_csv:
        return
    report = build_batch_report(job)
    if report_json:
        saved_json = write_report_atomic(
            Path(report_json), format_report_json(report), resolve_conflict=True
        )
        print(f"Đã lưu báo cáo JSON: {saved_json}")
    if report_csv:
        saved_csv = write_report_atomic(
            Path(report_csv), format_report_csv(report), resolve_conflict=True
        )
        print(f"Đã lưu báo cáo CSV: {saved_csv}")


def _convert_command(
    paths: Sequence[str],
    output_dir: str,
    ocr_language: str,
    *,
    dry_run: bool = False,
    report_json: str | None = None,
    report_csv: str | None = None,
    merge_images_name: str | None = None,
    target_format: str = "pdf",
) -> int:
    source_paths = [Path(value).expanduser().resolve(strict=True) for value in paths]
    if any(not path.is_file() for path in source_paths):
        raise ValueError("Mỗi đường dẫn đầu vào phải là một tệp.")
    destination = Path(output_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve(strict=True)
    job = create_batch_job(
        [_LocalUpload(path) for path in source_paths],
        destination,
        ocr_language,
        merge_images=(merge_images_name is not None),
        merged_pdf_name=(merge_images_name or "Anh-gop.pdf"),
        target_format=target_format,
    )
    try:
        for source in job.sources:
            label = SOURCE_STATUS_LABELS.get(source.status, source.status.value)
            proposed = f" -> {source.proposed_output_name}" if source.proposed_output_name else ""
            print(f"{source.original_name}: {label}{proposed}")

        if dry_run:
            for source in job.sources:
                for issue in source.issues:
                    if issue.message_vi:
                        print(f"{source.original_name}: {issue.message_vi}")
            _write_optional_reports(job, report_json, report_csv)
            has_problem = any(
                s.status in {SourceStatus.FAILED, SourceStatus.SKIPPED} for s in job.sources
            )
            return 1 if has_problem else 0

        valid_office = any(
            source.status is SourceStatus.VALID and source.extension in {".docx", ".xlsx", ".pptx"}
            for source in job.sources
        )
        valid_ocr = any(
            source.status is SourceStatus.VALID
            and (
                source.extension == ".pdf"
                or source.extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
            )
            for source in job.sources
        )
        executable = find_libreoffice() if valid_office else None
        ocr_executable = find_ocrmypdf() if valid_ocr else None
        office_converter = LibreOfficeConverter(executable=executable) if executable else None
        ocr_processor = OCRProcessor(executable=ocr_executable) if ocr_executable else None

        def progress(completed: int, total: int, source) -> None:
            status = SOURCE_STATUS_LABELS.get(source.status, source.status.value)
            print(f"[{completed}/{total}] {source.original_name}: {status}")

        convert_batch(job, office_converter, ocr_processor, progress)
        selected = {
            output.output_id
            for output in job.outputs
            if output.status in {OutputStatus.STAGED, OutputStatus.PREVIEWED}
        }
        chosen_names = [output.final_name for output in job.outputs if output.output_id in selected]
        if target_format == "docx":
            unique_names = resolve_unique_docx_names(chosen_names, destination) if chosen_names else []
        else:
            unique_names = resolve_unique_pdf_names(chosen_names, destination) if chosen_names else []
        final_names = {
            output.output_id: name
            for output, name in zip(
                (output for output in job.outputs if output.output_id in selected),
                unique_names,
                strict=True,
            )
        }
        commit_batch(job, selected, final_names)
        for output in job.outputs:
            status = OUTPUT_STATUS_LABELS.get(output.status, output.status.value)
            print(f"{output.final_name}: {status}")
            for issue in output.issues:
                if issue.message_vi:
                    print(f"  {issue.message_vi}")
        for source in job.sources:
            for issue in source.issues:
                if issue.message_vi:
                    print(f"{source.original_name}: {issue.message_vi}")
        _write_optional_reports(job, report_json, report_csv)
        print(f"Đã lưu {job.succeeded_count}/{len(job.sources)} PDF vào: {destination}")
        has_failed_or_skipped = (
            job.failed_count > 0
            or job.succeeded_count == 0
            or any(s.status in {SourceStatus.FAILED, SourceStatus.SKIPPED} for s in job.sources)
        )
        return 1 if has_failed_or_skipped else 0
    finally:
        if job.staging_dir is not None:
            cancel_batch(job)


def _resolve_ai_model(provider: str, model: str | None) -> str:
    if provider == "ollama":
        if model:
            return model
        models = list_local_models()
        if len(models) != 1:
            raise ValueError(
                "Hãy chỉ rõ --model; dùng 'officeflow ai models' để xem model Ollama đã cài."
            )
        return models[0]
    return model or os.environ.get("OFFICEFLOW_OPENAI_MODEL", "gpt-6-luna")


def _ai_command(
    pdf_paths: Sequence[str],
    provider: str,
    model: str | None,
    filter_request: str,
    allow_cloud: bool,
) -> int:
    if len(pdf_paths) > MAX_FILES_PER_BATCH:
        raise ValueError(f"Mỗi lượt phân loại nhận tối đa {MAX_FILES_PER_BATCH} tệp PDF.")
    if provider != "ollama" and not allow_cloud:
        raise ValueError(
            "Lệnh cloud cần cờ --allow-cloud để xác nhận gửi trích đoạn PDF ra ngoài máy."
        )

    resolved_paths: list[Path] = []
    for raw in pdf_paths:
        path = Path(raw).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            raise ValueError("Đầu vào của lệnh AI phải là một tệp PDF.")
        resolved_paths.append(path)

    resolved_model = _resolve_ai_model(provider, model)

    if len(resolved_paths) == 1:
        single_path = resolved_paths[0]
        if provider == "ollama":
            suggestion = suggest_filter(
                single_path, resolved_model, filter_request, single_path.stem
            )
        else:
            suggestion = suggest_filter_openai(
                single_path, resolved_model, filter_request, single_path.stem
            )
        print(
            json.dumps(
                {
                    "file": str(single_path),
                    "provider": provider,
                    "model": resolved_model,
                    "decision": suggestion.decision,
                    "category": suggestion.category,
                    "suggested_basename": suggestion.suggested_basename,
                    "reason": suggestion.reason,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    items = [(str(index), path, path.stem) for index, path in enumerate(resolved_paths, start=1)]
    batch_results = classify_pdf_batch(
        items,
        provider=provider,
        model=resolved_model,
        filter_request=filter_request,
        allow_cloud=allow_cloud,
    )
    succeeded = sum(1 for item in batch_results if item.suggestion is not None)
    failed = len(batch_results) - succeeded
    payload = {
        "provider": provider,
        "model": resolved_model,
        "filter": filter_request,
        "total": len(batch_results),
        "succeeded": succeeded,
        "failed": failed,
        "results": [
            {
                "file": str(item.pdf_path),
                "decision": item.suggestion.decision if item.suggestion else None,
                "category": item.suggestion.category if item.suggestion else None,
                "suggested_basename": (
                    item.suggestion.suggested_basename if item.suggestion else None
                ),
                "reason": item.suggestion.reason if item.suggestion else None,
                "error": item.error,
            }
            for item in batch_results
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failed > 0 else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="officeflow",
        description="Chuyển tài liệu sang PDF và gọi AI phân loại từ dòng lệnh.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    convert_parser = commands.add_parser("convert", help="Chuyển danh sách tệp sang PDF theo lô.")
    convert_parser.add_argument("files", nargs="+", help="Đường dẫn các tệp Office, PDF scan hoặc ảnh.")
    convert_parser.add_argument("--output-dir", required=True, help="Thư mục lưu PDF; tự tạo nếu chưa có.")
    convert_parser.add_argument("--ocr-language", choices=("vie", "eng", "vie+eng"), default="vie")
    convert_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ kiểm tra tệp và tên PDF dự kiến, không chuyển đổi hoặc ghi PDF.",
    )
    convert_parser.add_argument(
        "--report-json",
        help="Đường dẫn lưu báo cáo tổng kết lô dạng JSON (không ghi đè âm thầm).",
    )
    convert_parser.add_argument(
        "--report-csv",
        help="Đường dẫn lưu báo cáo tổng kết lô dạng CSV UTF-8 BOM cho Excel.",
    )
    convert_parser.add_argument(
        "--merge-images",
        metavar="NAME.pdf",
        default=None,
        help="Ghép tất cả ảnh scan hợp lệ trong lô thành một PDF nhiều trang với tên đã chỉ định.",
    )
    convert_parser.add_argument(
        "--to",
        choices=("pdf", "docx"),
        default="pdf",
        dest="target_format",
        help="Định dạng đầu ra: 'pdf' (mặc định) hoặc 'docx' (chuyển PDF sang Word giữ nguyên bảng biểu).",
    )

    doctor_parser = commands.add_parser(
        "doctor",
        help="Kiểm tra công cụ chuyển đổi, OCR, giao diện desktop và Ollama cục bộ.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Xuất báo cáo chẩn đoán dưới dạng JSON.",
    )
    doctor_parser.add_argument(
        "--strict",
        action="store_true",
        help="Trả mã thoát 1 nếu thiếu công cụ chuyển Office hoặc OCR bắt buộc.",
    )

    ai_parser = commands.add_parser("ai", help="Gọi model AI để phân loại nội dung PDF.")
    ai_commands = ai_parser.add_subparsers(dest="ai_command", required=True)
    models_parser = ai_commands.add_parser("models", help="Liệt kê model Ollama cục bộ.")
    models_parser.set_defaults(handler=_models_command)
    classify_parser = ai_commands.add_parser("classify", help="Gợi ý giữ/bỏ qua/xem lại và đặt tên PDF.")
    classify_parser.add_argument(
        "pdf",
        nargs="+",
        help="Một hoặc nhiều tệp PDF có lớp chữ, bao gồm PDF đã OCR.",
    )
    classify_parser.add_argument("--provider", choices=("ollama", "openai"), default="ollama")
    classify_parser.add_argument("--model", help="Tên model Ollama hoặc mã model OpenAI.")
    classify_parser.add_argument(
        "--filter",
        dest="filter_request",
        required=True,
        help="Tiêu chí phân loại tài liệu.",
    )
    classify_parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Xác nhận cho phép gửi trích đoạn PDF tới OpenAI API.",
    )
    return parser


def _models_command(_args: argparse.Namespace) -> int:
    models = list_local_models()
    print("\n".join(models) if models else "Chưa cài model Ollama nào.")
    return 0


def _doctor_command(*, as_json: bool = False, strict: bool = False) -> int:
    report = collect_doctor_report()
    print(format_doctor_json(report) if as_json else format_doctor_text(report))
    if strict:
        summary = report.get("summary", {})
        if not (summary.get("office_ready") and summary.get("ocr_ready")):
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    cleanup_orphaned_staging_once()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "convert":
            return _convert_command(
                args.files,
                args.output_dir,
                args.ocr_language,
                dry_run=args.dry_run,
                report_json=args.report_json,
                report_csv=args.report_csv,
                merge_images_name=args.merge_images,
                target_format=args.target_format,
            )
        if args.command == "doctor":
            return _doctor_command(as_json=args.as_json, strict=args.strict)
        if args.command == "ai" and args.ai_command == "models":
            return _models_command(args)
        if args.command == "ai" and args.ai_command == "classify":
            pdf_inputs = args.pdf if isinstance(args.pdf, list) else [args.pdf]
            return _ai_command(
                pdf_inputs,
                args.provider,
                args.model,
                args.filter_request,
                args.allow_cloud,
            )
    except (LocalAIError, OSError, RuntimeError, ValueError) as exc:
        print(f"OfficeFlow: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

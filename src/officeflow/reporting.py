"""Batch summary report builder and atomic JSON/CSV exporters."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .ai_filter import AIFilterSuggestion
from .messages_vi import BATCH_STATE_LABELS, OUTPUT_STATUS_LABELS, SOURCE_STATUS_LABELS
from .models import BatchJob

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lstrip(" \t\r\n").startswith(_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def build_batch_report(
    job: BatchJob,
    ai_suggestions: Mapping[str, AIFilterSuggestion] | None = None,
    *,
    ai_provider: str | None = None,
    ai_model: str | None = None,
) -> dict[str, Any]:
    """Build a privacy-safe metadata report for a batch without any extracted document text."""
    outputs_by_source = {
        sid: output for output in job.outputs for sid in output.related_source_ids
    }
    suggestions = dict(ai_suggestions or {})

    items: list[dict[str, Any]] = []
    for source in job.sources:
        output = outputs_by_source.get(source.source_id)
        suggestion = suggestions.get(output.output_id) if output is not None else None
        issues = [
            {
                "issue_code": issue.issue_code.value,
                "severity": issue.severity,
                "message_vi": issue.message_vi,
            }
            for issue in source.issues
        ]
        if output is not None:
            issues.extend(
                {
                    "issue_code": issue.issue_code.value,
                    "severity": issue.severity,
                    "message_vi": issue.message_vi,
                }
                for issue in output.issues
            )

        ai_payload: dict[str, Any] | None = None
        if suggestion is not None:
            ai_payload = {
                "provider": ai_provider or "",
                "model": ai_model or "",
                "decision": suggestion.decision,
                "category": suggestion.category,
                "suggested_basename": suggestion.suggested_basename,
                "reason": suggestion.reason,
            }

        items.append(
            {
                "source_id": source.source_id,
                "original_name": source.original_name,
                "extension": source.extension,
                "byte_size": source.byte_size,
                "source_status": source.status.value,
                "source_status_label_vi": SOURCE_STATUS_LABELS.get(source.status, source.status.value),
                "proposed_name": output.proposed_name if output else source.proposed_output_name,
                "output_id": output.output_id if output else None,
                "final_name": output.final_name if output else None,
                "output_status": output.status.value if output else None,
                "output_status_label_vi": (
                    OUTPUT_STATUS_LABELS.get(output.status, output.status.value) if output else None
                ),
                "destination_path": (
                    str(output.destination_path) if output and output.destination_path else None
                ),
                "page_count": output.page_count if output else None,
                "searchable_text": output.searchable_text if output else None,
                "issues": issues,
                "ai": ai_payload,
            }
        )

    return {
        "batch_id": job.batch_id,
        "created_at": job.created_at.isoformat(),
        "state": job.state.value,
        "state_label_vi": BATCH_STATE_LABELS.get(job.state, job.state.value),
        "destination": str(job.destination),
        "ocr_language": job.ocr_language,
        "counts": {
            "source_count": job.source_count,
            "succeeded_count": job.succeeded_count,
            "failed_count": job.failed_count,
            "skipped_count": job.skipped_count,
        },
        "items": items,
    }


def format_report_json(report: Mapping[str, Any]) -> bytes:
    """Serialize a batch report as UTF-8 JSON bytes."""
    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


def format_report_csv(report: Mapping[str, Any]) -> bytes:
    """Serialize a batch report as UTF-8 with BOM CSV bytes safe for Microsoft Excel."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "batch_id",
            "created_at",
            "original_name",
            "extension",
            "byte_size",
            "source_status",
            "final_name",
            "output_status",
            "destination_path",
            "page_count",
            "searchable_text",
            "ai_decision",
            "ai_category",
            "ai_suggested_basename",
            "ai_reason",
            "issues",
        ]
    )
    batch_id = report.get("batch_id", "")
    created_at = report.get("created_at", "")
    for item in report.get("items", []):
        if not isinstance(item, Mapping):
            continue
        ai = item.get("ai") if isinstance(item.get("ai"), Mapping) else {}
        issues = item.get("issues", [])
        issue_messages = "; ".join(
            str(issue.get("message_vi", ""))
            for issue in issues
            if isinstance(issue, Mapping) and issue.get("message_vi")
        )
        searchable = item.get("searchable_text")
        searchable_str = "" if searchable is None else ("true" if searchable else "false")
        writer.writerow(
            [
                _sanitize_csv_cell(batch_id),
                _sanitize_csv_cell(created_at),
                _sanitize_csv_cell(item.get("original_name")),
                _sanitize_csv_cell(item.get("extension")),
                _sanitize_csv_cell(item.get("byte_size")),
                _sanitize_csv_cell(item.get("source_status")),
                _sanitize_csv_cell(item.get("final_name") or item.get("proposed_name")),
                _sanitize_csv_cell(item.get("output_status")),
                _sanitize_csv_cell(item.get("destination_path")),
                _sanitize_csv_cell(item.get("page_count")),
                _sanitize_csv_cell(searchable_str),
                _sanitize_csv_cell(ai.get("decision") if ai else ""),
                _sanitize_csv_cell(ai.get("category") if ai else ""),
                _sanitize_csv_cell(ai.get("suggested_basename") if ai else ""),
                _sanitize_csv_cell(ai.get("reason") if ai else ""),
                _sanitize_csv_cell(issue_messages),
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def _unique_report_path(target_path: Path) -> Path:
    parent = target_path.parent
    stem = target_path.stem or "officeflow-report"
    suffix = target_path.suffix
    candidate = parent / f"{stem}{suffix}"
    serial = 1
    while candidate.exists():
        candidate = parent / f"{stem} ({serial}){suffix}"
        serial += 1
    return candidate


def write_report_atomic(
    target_path: Path, payload: bytes, *, resolve_conflict: bool = True
) -> Path:
    """Atomically write report bytes without silently overwriting an existing file."""
    expanded = Path(os.path.expandvars(str(target_path))).expanduser()
    parent = expanded.parent if str(expanded.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)
    parent_dir = parent.resolve(strict=True)
    final_path = parent_dir / expanded.name
    if resolve_conflict:
        final_path = _unique_report_path(final_path)
    elif final_path.exists():
        raise FileExistsError(f"Tệp báo cáo đã tồn tại: {final_path}")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".officeflow-report-", suffix=".tmp", dir=parent_dir, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        if os.name == "nt":
            os.rename(temp_path, final_path)
            temp_path = None
        else:
            os.link(temp_path, final_path)
        return final_path
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

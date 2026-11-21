"""Shared domain models for a local Office-to-PDF batch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


class BatchState(str, Enum):
    SELECTED = "selected"
    PREFLIGHT = "preflight"
    CONVERTING = "converting"
    REVIEW = "review"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SourceStatus(str, Enum):
    SELECTED = "selected"
    VALID = "valid"
    CONVERTING = "converting"
    CONVERTED = "converted"
    FAILED = "failed"
    SKIPPED = "skipped"


class OutputStatus(str, Enum):
    STAGED = "staged"
    PREVIEWED = "previewed"
    COMMITTED = "committed"
    DISCARDED = "discarded"
    FAILED = "failed"


class IssueCode(str, Enum):
    UNSUPPORTED_TYPE = "unsupported_type"
    UNREADABLE = "unreadable"
    PASSWORD_PROTECTED = "password_protected"
    CONVERSION_FAILED = "conversion_failed"
    OCR_FAILED = "ocr_failed"
    NAME_CONFLICT = "name_conflict"
    DESTINATION_ERROR = "destination_error"
    PREVIEW_WARNING = "preview_warning"


@dataclass(slots=True)
class ConversionIssue:
    issue_code: IssueCode
    severity: str
    message_vi: str
    source_id: str | None = None
    blocks_commit: bool = True


@dataclass(slots=True)
class SourceFile:
    source_id: str
    original_name: str
    extension: str
    byte_size: int
    source_location: Path | None = None
    status: SourceStatus = SourceStatus.SELECTED
    issues: list[ConversionIssue] = field(default_factory=list)
    proposed_output_name: str = ""


@dataclass(slots=True)
class OutputPdf:
    output_id: str
    source_id: str
    proposed_name: str
    final_name: str
    staging_path: Path | None
    destination_path: Path | None = None
    page_count: int | None = None
    searchable_text: bool | None = None
    status: OutputStatus = OutputStatus.STAGED
    issues: list[ConversionIssue] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    table_count: int | None = None
    preview_blocks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def related_source_ids(self) -> list[str]:
        return self.source_ids if self.source_ids else ([self.source_id] if self.source_id else [])


@dataclass(slots=True)
class BatchJob:
    batch_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    destination: Path = Path()
    state: BatchState = BatchState.SELECTED
    ocr_language: str = "vie"
    sources: list[SourceFile] = field(default_factory=list)
    outputs: list[OutputPdf] = field(default_factory=list)
    staging_dir: Path | None = None
    current_source_id: str | None = None
    issues: list[ConversionIssue] = field(default_factory=list)
    merge_images: bool = False
    merged_pdf_name: str = "Anh-gop.pdf"
    target_format: str = "pdf"

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def succeeded_count(self) -> int:
        return sum(item.status is OutputStatus.COMMITTED for item in self.outputs)

    @property
    def failed_count(self) -> int:
        failed_ids = {
            item.source_id for item in self.sources if item.status is SourceStatus.FAILED
        }
        for item in self.outputs:
            if item.status is OutputStatus.FAILED:
                failed_ids.update(item.related_source_ids)
        return len(failed_ids)

    @property
    def skipped_count(self) -> int:
        skipped_ids = {
            item.source_id for item in self.sources if item.status is SourceStatus.SKIPPED
        }
        for item in self.outputs:
            if item.status is OutputStatus.DISCARDED:
                skipped_ids.update(item.related_source_ids)
        return len(skipped_ids)

    @property
    def committed_count(self) -> int:
        return self.succeeded_count

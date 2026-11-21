"""Unit tests for staging lifecycle, batch fault isolation, TOCTOU commits, and reporting."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from officeflow.ai_filter import AIFilterSuggestion
from officeflow.batch import (
    cancel_batch,
    commit_batch,
    convert_batch,
    create_batch_job,
    create_retry_batch,
)
from officeflow.converter import ConversionError, ConversionResult
from officeflow.models import BatchState, IssueCode, OutputPdf, OutputStatus, SourceStatus
from officeflow.reporting import (
    build_batch_report,
    format_report_csv,
    format_report_json,
    write_report_atomic,
)
import officeflow.staging as staging


def _valid_docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


class _MemoryUpload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self._data


class _StubConverter:
    def __init__(self, fail_names: set[str] | None = None) -> None:
        self.fail_names = fail_names or set()

    def convert_to_pdf(self, source_path: Path, output_dir: Path) -> ConversionResult:
        if any(source_path.name.endswith(name) for name in self.fail_names):
            raise ConversionError("Lỗi chuyển đổi giả lập.", IssueCode.CONVERSION_FAILED)
        pdf_path = output_dir / f"{source_path.stem}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
        return ConversionResult(pdf_path=pdf_path, page_count=2)


class TestStagingBatchAndReporting(unittest.TestCase):
    def test_commit_staged_pdf_cleans_temp_file_on_write_error_and_prevents_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / "staged.pdf"
            staged.write_bytes(b"%PDF-1.4\nnew-content\n")
            dest = root / "dest"
            dest.mkdir()
            existing = dest / "Bao-cao.pdf"
            existing.write_bytes(b"%PDF-1.4\noriginal-content\n")

            output = OutputPdf(
                output_id="out1",
                source_id="src1",
                proposed_name="Bao-cao.pdf",
                final_name="Bao-cao.pdf",
                staging_path=staged,
            )
            with self.assertRaises(FileExistsError):
                staging.commit_staged_pdf(output, dest, "Bao-cao.pdf")
            self.assertEqual(existing.read_bytes(), b"%PDF-1.4\noriginal-content\n")
            self.assertEqual(list(dest.glob(".officeflow-*.tmp")), [])

            # Simulate copyfileobj OSError -> ensure no .officeflow-*.tmp left behind
            with mock.patch("officeflow.staging.shutil.copyfileobj", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    staging.commit_staged_pdf(output, dest, "Moi.pdf")
            self.assertEqual(list(dest.glob(".officeflow-*.tmp")), [])

    def test_orphan_staging_cleanup_removes_only_expired_batch_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp) / "staging"
            fake_root.mkdir()
            old_batch = fake_root / "batch-old123"
            fresh_batch = fake_root / "batch-fresh456"
            unrelated = fake_root / "other-folder"
            old_batch.mkdir()
            fresh_batch.mkdir()
            unrelated.mkdir()
            old_time = time.time() - (72 * 3600)
            os.utime(old_batch, (old_time, old_time))
            os.utime(unrelated, (old_time, old_time))

            with mock.patch.object(staging, "STAGING_ROOT", fake_root):
                removed = staging.cleanup_orphaned_staging(max_age_hours=48)
                self.assertEqual(removed, 1)
                self.assertFalse(old_batch.exists())
                self.assertTrue(fresh_batch.exists())
                self.assertTrue(unrelated.exists())

    def test_batch_isolation_toctou_conflict_and_retry_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            uploads = [
                _MemoryUpload("Hop-le-1.docx", _valid_docx_bytes()),
                _MemoryUpload("Hop-le-2.docx", _valid_docx_bytes()),
                _MemoryUpload("Hong.docx", b"not-a-zip"),
                _MemoryUpload("Macro.docm", b"macro"),
            ]
            job = create_batch_job(uploads, dest, ocr_language="vie")
            convert_batch(job, _StubConverter())
            self.assertEqual(len(job.outputs), 2)

            # Simulate TOCTOU collision on Hop-le-2.pdf right before commit_batch
            (dest / "Hop-le-2.pdf").write_bytes(b"existing")
            selected = {o.output_id for o in job.outputs}
            final_names = {o.output_id: o.final_name for o in job.outputs}
            commit_batch(job, selected, final_names)

            self.assertIs(job.state, BatchState.COMMITTED)
            self.assertEqual(job.succeeded_count, 1)
            self.assertEqual(job.failed_count, 2)  # Hong.docx + Hop-le-2.pdf conflict
            self.assertEqual(job.skipped_count, 1)  # Macro.docm
            self.assertEqual((dest / "Hop-le-2.pdf").read_bytes(), b"existing")

            # Retry batch allows switching OCR language and rejects non-failed names
            with self.assertRaises(ValueError):
                create_retry_batch(job, [_MemoryUpload("Hop-le-1.docx", _valid_docx_bytes())], dest)
            retry_job = create_retry_batch(
                job,
                [_MemoryUpload("Hong.docx", _valid_docx_bytes())],
                dest,
                ocr_language="vie+eng",
            )
            self.assertEqual(retry_job.ocr_language, "vie+eng")
            cancel_batch(retry_job)

    def test_reporting_csv_formula_sanitization_and_atomic_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            uploads = [_MemoryUpload("=SUM(1,2).docx", _valid_docx_bytes())]
            job = create_batch_job(uploads, dest, ocr_language="vie")
            convert_batch(job, _StubConverter())
            out_id = job.outputs[0].output_id
            suggestions = {
                out_id: AIFilterSuggestion(
                    decision="keep",
                    category="Hành chính",
                    suggested_basename="Bao-cao-2026",
                    reason="+Lý do bắt đầu bằng dấu cộng",
                )
            }
            report = build_batch_report(
                job, suggestions, ai_provider="ollama", ai_model="qwen3.5:4b"
            )
            csv_bytes = format_report_csv(report)
            self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
            csv_text = csv_bytes.decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(csv_text)))
            self.assertEqual(len(rows), 2)
            # Both formula-prefixed cells must be escaped with leading apostrophe
            self.assertTrue(rows[1][2].startswith("'=SUM"))
            self.assertTrue(rows[1][14].startswith("'+Lý do"))

            json_bytes = format_report_json(report)
            parsed = json.loads(json_bytes.decode("utf-8"))
            self.assertEqual(parsed["counts"]["source_count"], 1)

            r1 = write_report_atomic(dest / "report.json", json_bytes, resolve_conflict=True)
            r2 = write_report_atomic(dest / "report.json", json_bytes, resolve_conflict=True)
            self.assertEqual(r1.name, "report.json")
            self.assertEqual(r2.name, "report (1).json")
            with self.assertRaises(FileExistsError):
                write_report_atomic(dest / "report.json", json_bytes, resolve_conflict=False)
            cancel_batch(job)


if __name__ == "__main__":
    unittest.main()

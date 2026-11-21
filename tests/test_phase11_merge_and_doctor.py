"""Unit and integration tests for Phase 11: Multi-image merge OCR and `officeflow doctor`."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw
from pypdf import PdfWriter

from officeflow.batch import cancel_batch, commit_batch, convert_batch, create_batch_job
from officeflow.cli import main as cli_main
from officeflow.converter import ConversionError, ConversionResult
from officeflow.doctor import collect_doctor_report
from officeflow.models import IssueCode, SourceStatus
from officeflow.ocr import OCRProcessor, find_ocrmypdf, find_tesseract
from officeflow.reporting import build_batch_report


def _valid_docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def _valid_png_bytes(text: str = "TRANG SCAN 2026") -> bytes:
    img = Image.new("RGB", (600, 220), "white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 80), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()


class _MemoryUpload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self._data


class _StubOfficeConverter:
    def convert_to_pdf(self, source_path: Path, output_dir: Path) -> ConversionResult:
        pdf_path = output_dir / f"{source_path.stem}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with pdf_path.open("wb") as handle:
            writer.write(handle)
        return ConversionResult(pdf_path=pdf_path, page_count=1)


class _StubOCRProcessor:
    def __init__(self, fail_on_merge: bool = False, fail_source_Substring: str | None = None) -> None:
        self.fail_on_merge = fail_on_merge
        self.fail_source_substring = fail_source_Substring

    def process(self, source_path: Path, output_path: Path, language: str = "vie") -> ConversionResult:
        if self.fail_source_substring and self.fail_source_substring in source_path.name:
            raise ConversionError("Ảnh hỏng giả lập.", IssueCode.OCR_FAILED)
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with output_path.open("wb") as handle:
            writer.write(handle)
        return ConversionResult(pdf_path=output_path, page_count=1, searchable_text_chars=25)

    def merge_images_to_pdf(
        self, image_paths, output_path: Path, language: str = "vie"
    ) -> ConversionResult:
        if self.fail_on_merge:
            raise ConversionError("Lỗi ghép nhóm giả lập để kiểm tra fallback.", IssueCode.OCR_FAILED)
        writer = PdfWriter()
        for _ in image_paths:
            writer.add_blank_page(width=200, height=200)
        with output_path.open("wb") as handle:
            writer.write(handle)
        return ConversionResult(
            pdf_path=output_path,
            page_count=len(image_paths),
            searchable_text_chars=30 * len(image_paths),
        )


class TestPhase11MergeAndDoctor(unittest.TestCase):
    def test_doctor_command_json_and_secret_redaction(self) -> None:
        secret = "sk-super-secret-do-not-print-12345"
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli_main(["doctor", "--json"])
            self.assertEqual(rc, 0)
            raw_output = buf.getvalue()
            self.assertNotIn(secret, raw_output)
            parsed = json.loads(raw_output)
            self.assertEqual(parsed["schema_version"], "1.0")
            self.assertTrue(parsed["checks"]["openai"]["details"]["api_key_configured"])

            buf_text = io.StringIO()
            with redirect_stdout(buf_text):
                rc_text = cli_main(["doctor"])
            self.assertEqual(rc_text, 0)
            self.assertNotIn(secret, buf_text.getvalue())
            self.assertIn("OfficeFlow Doctor", buf_text.getvalue())

    def test_mixed_batch_multi_image_merge_and_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            uploads = [
                _MemoryUpload("Bao-cao.docx", _valid_docx_bytes()),
                _MemoryUpload("Trang-1.png", _valid_png_bytes("TRANG 1")),
                _MemoryUpload("Trang-2.png", _valid_png_bytes("TRANG 2")),
            ]
            job = create_batch_job(
                uploads,
                dest,
                ocr_language="vie",
                merge_images=True,
                merged_pdf_name="Ho-so-ghep.pdf",
            )
            self.assertTrue(job.merge_images)
            self.assertEqual(job.merged_pdf_name, "Ho-so-ghep.pdf")
            convert_batch(job, _StubOfficeConverter(), _StubOCRProcessor())

            # 1 DOCX output + 1 merged image output = 2 outputs total
            self.assertEqual(len(job.outputs), 2)
            by_name = {o.final_name: o for o in job.outputs}
            self.assertIn("Bao-cao.pdf", by_name)
            self.assertIn("Ho-so-ghep.pdf", by_name)
            merged_out = by_name["Ho-so-ghep.pdf"]
            self.assertEqual(merged_out.page_count, 2)
            self.assertEqual(len(merged_out.related_source_ids), 2)

            report = build_batch_report(job)
            self.assertEqual(len(report["items"]), 3)
            for item in report["items"][1:]:
                self.assertEqual(item["final_name"], "Ho-so-ghep.pdf")

            selected = {o.output_id for o in job.outputs}
            final_names = {o.output_id: o.final_name for o in job.outputs}
            commit_batch(job, selected, final_names)
            self.assertEqual(job.succeeded_count, 2)
            self.assertTrue((dest / "Ho-so-ghep.pdf").is_file())

    def test_multi_image_merge_per_image_error_isolation_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            uploads = [
                _MemoryUpload("Anh-1.png", _valid_png_bytes("ANH 1")),
                _MemoryUpload("Anh-loi.png", _valid_png_bytes("ANH LOI")),
                _MemoryUpload("Anh-2.png", _valid_png_bytes("ANH 2")),
            ]
            job = create_batch_job(
                uploads,
                dest,
                ocr_language="vie",
                merge_images=True,
                merged_pdf_name="Ghep-con-lai.pdf",
            )
            stub_ocr = _StubOCRProcessor(fail_on_merge=True, fail_source_Substring="Anh-loi")
            convert_batch(job, None, stub_ocr)

            self.assertEqual(len(job.outputs), 1)
            self.assertEqual(job.outputs[0].page_count, 2)
            self.assertEqual(len(job.outputs[0].related_source_ids), 2)
            statuses = {s.original_name: s.status for s in job.sources}
            self.assertEqual(statuses["Anh-1.png"], SourceStatus.CONVERTED)
            self.assertEqual(statuses["Anh-loi.png"], SourceStatus.FAILED)
            self.assertEqual(statuses["Anh-2.png"], SourceStatus.CONVERTED)
            cancel_batch(job)

    @unittest.skipUnless(
        find_ocrmypdf() and find_tesseract(),
        "OCRmyPDF and Tesseract required for real multi-image merge OCR test",
    )
    def test_real_ocr_merge_images_to_two_page_searchable_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            img1 = tmp_dir / "page1.png"
            img2 = tmp_dir / "page2.png"
            img1.write_bytes(_valid_png_bytes("HO SO TRANG MOT NAM 2026"))
            img2.write_bytes(_valid_png_bytes("HO SO TRANG HAI NAM 2026"))

            out_dir = tmp_dir / "out"
            rc = cli_main(
                [
                    "convert",
                    str(img1),
                    str(img2),
                    "--output-dir",
                    str(out_dir),
                    "--ocr-language",
                    "vie",
                    "--merge-images",
                    "Ghep-2-trang.pdf",
                ]
            )
            self.assertEqual(rc, 0)
            merged_pdf = out_dir / "Ghep-2-trang.pdf"
            self.assertTrue(merged_pdf.is_file())

    def test_pdf_to_word_docx_preserves_tables_and_commits_cleanly(self) -> None:
        sample_pdf = Path(
            r"C:\Users\huu66\.gemini\antigravity\brain\df4a3479-5bf2-43b4-ab6b-28a1b5c43d6f\scratch\live_show\Bang-ke-chi-phi-2026.pdf"
        )
        if not sample_pdf.is_file():
            return
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "word_out"
            rc = cli_main(
                [
                    "convert",
                    str(sample_pdf),
                    "--output-dir",
                    str(out_dir),
                    "--to",
                    "docx",
                ]
            )
            self.assertEqual(rc, 0)
            out_docx = out_dir / "Bang-ke-chi-phi-2026.docx"
            self.assertTrue(out_docx.is_file())
            with zipfile.ZipFile(out_docx) as zf:
                doc_xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("<w:tbl>", doc_xml)
                self.assertIn("4500000", doc_xml)


if __name__ == "__main__":
    unittest.main()

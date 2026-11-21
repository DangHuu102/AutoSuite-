"""Integration tests against local LibreOffice and OCRmyPDF/Tesseract using synthetic samples."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from officeflow.ai_filter import extract_pdf_excerpt
from officeflow.converter import LibreOfficeConverter, find_libreoffice
from officeflow.ocr import OCRProcessor, find_ocrmypdf, find_tesseract

SYNTHETIC_DIR = Path(__file__).resolve().parents[1] / "sample-documents" / "synthetic"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestIntegrationConverters(unittest.TestCase):
    @unittest.skipUnless(find_libreoffice(), "LibreOffice is required for Office integration tests")
    def test_libreoffice_converts_docx_xlsx_and_excludes_hidden_pptx_slide(self) -> None:
        converter = LibreOfficeConverter()
        docx = SYNTHETIC_DIR / "Bao-cao-hanh-chinh-2026.docx"
        xlsx = SYNTHETIC_DIR / "Bang-ke-chi-phi-2026.xlsx"
        pptx = SYNTHETIC_DIR / "Trinh-chieu-ke-hoach-2026.pptx"
        before = {p: _sha256(p) for p in (docx, xlsx, pptx)}

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            res_docx = converter.convert_to_pdf(docx, out_dir / "docx")
            res_xlsx = converter.convert_to_pdf(xlsx, out_dir / "xlsx")
            res_pptx = converter.convert_to_pdf(pptx, out_dir / "pptx")

            self.assertEqual(res_docx.page_count, 1)
            self.assertEqual(res_xlsx.page_count, 2)
            self.assertEqual(res_pptx.page_count, 1)
            self.assertIn("2026", extract_pdf_excerpt(res_docx.pdf_path))

        for p, digest in before.items():
            self.assertEqual(_sha256(p), digest)

    @unittest.skipUnless(
        find_ocrmypdf() and find_tesseract(),
        "OCRmyPDF and Tesseract are required for OCR integration tests",
    )
    def test_ocrmypdf_adds_vietnamese_searchable_text_to_scan_pdf_and_png(self) -> None:
        processor = OCRProcessor()
        scan_pdf = SYNTHETIC_DIR / "Ho-so-scan-2-trang.pdf"
        scan_png = SYNTHETIC_DIR / "Giay-de-nghi-thanh-toan.png"
        before = {p: _sha256(p) for p in (scan_pdf, scan_png)}

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            res_pdf = processor.process(scan_pdf, out_dir / "scan.pdf", language="vie")
            res_png = processor.process(scan_png, out_dir / "img.pdf", language="vie")

            self.assertEqual(res_pdf.page_count, 2)
            self.assertGreater(res_pdf.searchable_text_chars or 0, 20)
            self.assertEqual(res_png.page_count, 1)
            self.assertGreater(res_png.searchable_text_chars or 0, 20)
            self.assertIn("2026", extract_pdf_excerpt(res_png.pdf_path))

        for p, digest in before.items():
            self.assertEqual(_sha256(p), digest)


if __name__ == "__main__":
    unittest.main()

"""Unit tests for naming collision safety and source file preflight validation."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

from officeflow.models import IssueCode, SourceFile, SourceStatus
from officeflow.naming import (
    normalize_pdf_name,
    propose_output_names,
    resolve_unique_pdf_names,
    safe_source_filename,
)
from officeflow.validation import apply_preflight, validate_source


class TestNaming(unittest.TestCase):
    def test_vietnamese_diacritics_and_dot_separated_stems_preserved(self) -> None:
        self.assertEqual(
            normalize_pdf_name("Báo cáo tài chính Q4.2026"),
            "Báo cáo tài chính Q4.2026.pdf",
        )
        self.assertEqual(
            normalize_pdf_name("Hop-dong.v2.pdf"),
            "Hop-dong.v2.pdf",
        )
        self.assertEqual(
            normalize_pdf_name("Bao-cao.docx"),
            "Bao-cao.pdf",
        )

    def test_path_traversal_rejected_in_normalize_pdf_name(self) -> None:
        for bad in ("../../secret.pdf", r"C:\Windows\System32\x.pdf", "folder/file.pdf"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    normalize_pdf_name(bad)

    def test_safe_source_filename_strips_paths_and_clamps_stem(self) -> None:
        self.assertEqual(safe_source_filename("../../Bao<cao>:2026?.docx"), "Bao_cao__2026_.docx")
        short = safe_source_filename("A" * 200 + ".xlsx", max_stem_length=48)
        self.assertEqual(short, ("A" * 48) + ".xlsx")

    def test_windows_reserved_device_names_and_empty_stems(self) -> None:
        self.assertEqual(normalize_pdf_name("CON.pdf"), "_CON.pdf")
        self.assertEqual(normalize_pdf_name("lpt1"), "_lpt1.pdf")
        self.assertEqual(normalize_pdf_name("   ...   "), "tai-lieu.pdf")

    def test_max_length_clamping_with_collision_suffixes(self) -> None:
        long_stem = "Báo-cáo-" + ("A" * 220)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            resolved = resolve_unique_pdf_names([f"{long_stem}.pdf", f"{long_stem}.pdf"], dest)
            self.assertEqual(len(resolved), 2)
            self.assertNotEqual(resolved[0].casefold(), resolved[1].casefold())
            for name in resolved:
                self.assertLessEqual(len(name), 180)
                self.assertTrue(name.endswith(".pdf"))

    def test_case_insensitive_in_batch_and_destination_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "Bao-cao.pdf").write_bytes(b"%PDF-1.4")
            (dest / "BAO-CAO (1).PDF").write_bytes(b"%PDF-1.4")
            proposed = propose_output_names(
                ["Bao-cao.docx", "bao-cao.xlsx", "Bao-cao (1).pptx"],
                dest,
            )
            self.assertEqual(
                proposed,
                ["Bao-cao (2).pdf", "bao-cao (3).pdf", "Bao-cao (1) (1).pdf"],
            )


class TestValidation(unittest.TestCase):
    def _make_source(self, path: Path) -> SourceFile:
        return SourceFile(
            source_id="src1",
            original_name=path.name,
            extension=path.suffix.casefold(),
            byte_size=path.stat().st_size if path.exists() else 0,
            source_location=path,
        )

    def test_unsupported_legacy_and_macro_extensions_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for ext in (".doc", ".xls", ".ppt", ".docm", ".xlsm", ".pptm", ".gif", ".heic"):
                path = Path(tmp) / f"sample{ext}"
                path.write_bytes(b"dummy content")
                src = apply_preflight(self._make_source(path))
                self.assertIs(src.status, SourceStatus.SKIPPED)
                self.assertEqual(src.issues[0].issue_code, IssueCode.UNSUPPORTED_TYPE)

    def test_zero_byte_and_corrupted_ooxml_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_docx = Path(tmp) / "empty.docx"
            empty_docx.write_bytes(b"")
            src_empty = apply_preflight(self._make_source(empty_docx))
            self.assertIs(src_empty.status, SourceStatus.FAILED)
            self.assertEqual(src_empty.issues[0].issue_code, IssueCode.UNREADABLE)

            wrong_part = Path(tmp) / "wrong.xlsx"
            with zipfile.ZipFile(wrong_part, "w") as zf:
                zf.writestr("[Content_Types].xml", "<Types/>")
                zf.writestr("_rels/.rels", "<Relationships/>")
                zf.writestr("word/document.xml", "<w:document/>")
            src_wrong = apply_preflight(self._make_source(wrong_part))
            self.assertIs(src_wrong.status, SourceStatus.FAILED)
            self.assertEqual(src_wrong.issues[0].issue_code, IssueCode.UNREADABLE)

    def test_encrypted_pdf_cfb_and_encrypted_zip_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # 1. Encrypted PDF
            enc_pdf = Path(tmp) / "locked.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.encrypt("secret")
            with enc_pdf.open("wb") as handle:
                writer.write(handle)
            src_pdf = apply_preflight(self._make_source(enc_pdf))
            self.assertIs(src_pdf.status, SourceStatus.FAILED)
            self.assertEqual(src_pdf.issues[0].issue_code, IssueCode.PASSWORD_PROTECTED)

            # 2. CFB encrypted Office container signature
            cfb_docx = Path(tmp) / "encrypted.docx"
            cfb_docx.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 64)
            src_cfb = apply_preflight(self._make_source(cfb_docx))
            self.assertIs(src_cfb.status, SourceStatus.FAILED)
            self.assertEqual(src_cfb.issues[0].issue_code, IssueCode.PASSWORD_PROTECTED)

    def test_multiframe_tiff_rejected_and_singleframe_tiff_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            multi = Path(tmp) / "multi.tiff"
            img1 = Image.new("RGB", (64, 64), "white")
            img2 = Image.new("RGB", (64, 64), "black")
            img1.save(multi, save_all=True, append_images=[img2])
            src_multi = apply_preflight(self._make_source(multi))
            self.assertIs(src_multi.status, SourceStatus.SKIPPED)
            self.assertEqual(src_multi.issues[0].issue_code, IssueCode.UNSUPPORTED_TYPE)

            single = Path(tmp) / "single.tif"
            img1.save(single)
            src_single = apply_preflight(self._make_source(single))
            self.assertIs(src_single.status, SourceStatus.VALID)
            self.assertEqual(validate_source(src_single), [])


if __name__ == "__main__":
    unittest.main()

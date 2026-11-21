"""Convert PDF documents (including scanned PDFs via OCR) to Word (.docx) while preserving tables."""

from __future__ import annotations

from dataclasses import dataclass, field
import html
import tempfile
import zipfile
from pathlib import Path
from typing import Sequence

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .converter import ConversionError, ConversionResult
from .models import IssueCode
from .ocr import OCRProcessor


@dataclass(slots=True)
class _TextSpan:
    x: float
    y: float
    text: str
    font_size: float = 11.0


@dataclass(slots=True)
class _PageBlock:
    is_table: bool
    rows: list[list[str]] = field(default_factory=list)
    paragraph_text: str = ""
    is_heading: bool = False


@dataclass(slots=True)
class WordConversionResult:
    docx_path: Path
    page_count: int
    table_count: int
    paragraph_count: int
    preview_blocks: list[dict[str, object]] = field(default_factory=list)


def _extract_page_spans(page) -> list[_TextSpan]:
    spans: list[_TextSpan] = []

    def _visitor(text: str, _cm, tm, _font_dict, font_size: float) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        x = float(tm[4]) if tm and len(tm) >= 6 else 0.0
        y = float(tm[5]) if tm and len(tm) >= 6 else 0.0
        size = float(font_size) if font_size and font_size > 0 else 11.0
        spans.append(_TextSpan(x=x, y=y, text=cleaned, font_size=size))

    try:
        page.extract_text(visitor_text=_visitor)
    except Exception:
        fallback_text = (page.extract_text() or "").strip()
        for idx, line in enumerate(fallback_text.splitlines()):
            if line.strip():
                spans.append(_TextSpan(x=50.0, y=800.0 - idx * 14.0, text=line.strip()))
    return spans


def _group_spans_into_lines(
    spans: Sequence[_TextSpan], y_tolerance: float = 4.5
) -> list[list[_TextSpan]]:
    if not spans:
        return []
    sorted_spans = sorted(spans, key=lambda s: (-s.y, s.x))
    lines: list[list[_TextSpan]] = []
    current_line: list[_TextSpan] = [sorted_spans[0]]
    current_y = sorted_spans[0].y

    for span in sorted_spans[1:]:
        if abs(span.y - current_y) <= y_tolerance:
            current_line.append(span)
        else:
            lines.append(sorted(current_line, key=lambda s: s.x))
            current_line = [span]
            current_y = span.y
    if current_line:
        lines.append(sorted(current_line, key=lambda s: s.x))

    # Merge adjacent spans on the same line that are very close horizontally (< 8 pt gap)
    merged_lines: list[list[_TextSpan]] = []
    for line in lines:
        merged: list[_TextSpan] = [line[0]]
        for span in line[1:]:
            prev = merged[-1]
            est_prev_end = prev.x + max(len(prev.text) * (prev.font_size * 0.45), 10.0)
            if span.x - est_prev_end < 8.0:
                merged[-1] = _TextSpan(
                    x=prev.x,
                    y=prev.y,
                    text=f"{prev.text} {span.text}".strip(),
                    font_size=max(prev.font_size, span.font_size),
                )
            else:
                merged.append(span)
        merged_lines.append(merged)
    return merged_lines


def _cluster_column_anchors(table_lines: Sequence[Sequence[_TextSpan]], x_tolerance: float = 24.0) -> list[float]:
    xs = sorted(span.x for line in table_lines for span in line)
    if not xs:
        return [0.0]
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if abs(x - (sum(clusters[-1]) / len(clusters[-1]))) <= x_tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _build_table_block(table_lines: Sequence[Sequence[_TextSpan]]) -> _PageBlock:
    anchors = _cluster_column_anchors(table_lines)
    col_count = max(len(anchors), 2)
    rows: list[list[str]] = []
    for line in table_lines:
        row_cells = [""] * col_count
        for span in line:
            best_col = min(range(len(anchors)), key=lambda idx: abs(span.x - anchors[idx]))
            if row_cells[best_col]:
                row_cells[best_col] = f"{row_cells[best_col]} {span.text}".strip()
            else:
                row_cells[best_col] = span.text
        rows.append(row_cells)
    return _PageBlock(is_table=True, rows=rows)


def _analyze_page_blocks(spans: Sequence[_TextSpan]) -> list[_PageBlock]:
    lines = _group_spans_into_lines(spans)
    if not lines:
        return []

    blocks: list[_PageBlock] = []
    pending_table_lines: list[list[_TextSpan]] = []

    def _flush_table() -> None:
        nonlocal pending_table_lines
        if not pending_table_lines:
            return
        if len(pending_table_lines) >= 1 and any(len(line) >= 2 for line in pending_table_lines):
            blocks.append(_build_table_block(pending_table_lines))
        else:
            for line in pending_table_lines:
                text = " ".join(s.text for s in line).strip()
                if text:
                    blocks.append(_PageBlock(is_table=False, paragraph_text=text))
        pending_table_lines = []

    for line in lines:
        if len(line) >= 2:
            pending_table_lines.append(line)
        else:
            _flush_table()
            single = line[0]
            is_heading = single.font_size >= 13.5 or (
                len(single.text) <= 90 and single.text == single.text.upper() and any(c.isalpha() for c in single.text)
            )
            blocks.append(
                _PageBlock(
                    is_table=False,
                    paragraph_text=single.text,
                    is_heading=is_heading,
                )
            )
    _flush_table()
    return blocks


def _xml_paragraph(text: str, *, bold: bool = False, font_size_half_pts: int = 22) -> str:
    escaped = html.escape(text)
    b_tag = "<w:b/>" if bold else ""
    return (
        "<w:p>"
        "<w:pPr><w:spacing w:after=\"120\"/></w:pPr>"
        "<w:r>"
        f"<w:rPr>{b_tag}<w:sz w:val=\"{font_size_half_pts}\"/><w:szCs w:val=\"{font_size_half_pts}\"/></w:rPr>"
        f"<w:t xml:space=\"preserve\">{escaped}</w:t>"
        "</w:r>"
        "</w:p>"
    )


def _xml_table(rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    col_width = max(int(9000 / max(col_count, 1)), 1200)
    grid_cols = "".join(f"<w:gridCol w:w=\"{col_width}\"/>" for _ in range(col_count))
    borders = (
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"8FA3BF\"/>"
        "<w:left w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"8FA3BF\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"8FA3BF\"/>"
        "<w:right w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"8FA3BF\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"BFD0E6\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"BFD0E6\"/>"
        "</w:tblBorders>"
    )
    tr_xmls: list[str] = []
    for row_idx, row in enumerate(rows):
        tc_xmls: list[str] = []
        is_header = row_idx == 0 and len(rows) > 1
        shading = "<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"EDF3FF\"/>" if is_header else ""
        for col_idx in range(col_count):
            cell_text = row[col_idx] if col_idx < len(row) else ""
            p_xml = _xml_paragraph(cell_text, bold=is_header, font_size_half_pts=21)
            tc_xmls.append(
                "<w:tc>"
                f"<w:tcPr><w:tcW w:w=\"{col_width}\" w:type=\"dxa\"/>{shading}</w:tcPr>"
                f"{p_xml}"
                "</w:tc>"
            )
        tr_xmls.append("<w:tr>" + "".join(tc_xmls) + "</w:tr>")

    return (
        "<w:tbl>"
        "<w:tblPr>"
        "<w:tblW w:w=\"9000\" w:type=\"dxa\"/>"
        f"{borders}"
        "<w:tblCellMar>"
        "<w:top w:w=\"80\" w:type=\"dxa\"/>"
        "<w:left w:w=\"120\" w:type=\"dxa\"/>"
        "<w:bottom w:w=\"80\" w:type=\"dxa\"/>"
        "<w:right w:w=\"120\" w:type=\"dxa\"/>"
        "</w:tblCellMar>"
        "</w:tblPr>"
        f"<w:tblGrid>{grid_cols}</w:tblGrid>"
        + "".join(tr_xmls)
        + "</w:tbl>"
        "<w:p/>"
    )


def _write_ooxml_docx(output_path: Path, pages_blocks: Sequence[Sequence[_PageBlock]]) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    body_parts: list[str] = []
    total_pages = len(pages_blocks)
    for page_index, blocks in enumerate(pages_blocks):
        if not blocks:
            body_parts.append(_xml_paragraph(""))
        for block in blocks:
            if block.is_table:
                body_parts.append(_xml_table(block.rows))
            else:
                body_parts.append(
                    _xml_paragraph(
                        block.paragraph_text,
                        bold=block.is_heading,
                        font_size_half_pts=26 if block.is_heading else 22,
                    )
                )
        if page_index + 1 < total_pages:
            body_parts.append("<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>")

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>"
        + "".join(body_parts)
        + "<w:sectPr>"
        "<w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" w:left=\"1134\"/>"
        "</w:sectPr>"
        "</w:body>"
        "</w:document>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)


def convert_pdf_to_docx(
    pdf_path: Path,
    output_docx_path: Path,
    *,
    ocr_processor: OCRProcessor | None = None,
    ocr_language: str = "vie",
) -> WordConversionResult:
    """Convert a PDF file to an editable Word (.docx) file while preserving tables and text."""
    if not pdf_path.is_file() or pdf_path.suffix.casefold() != ".pdf":
        raise ConversionError("Chế độ PDF sang Word chỉ nhận tệp .pdf.", IssueCode.UNSUPPORTED_TYPE)

    try:
        reader = PdfReader(str(pdf_path), strict=False)
        if reader.is_encrypted:
            raise ConversionError(
                "PDF được bảo vệ bằng mật khẩu; hãy mở khóa trước khi chuyển sang Word.",
                IssueCode.PASSWORD_PROTECTED,
            )
        page_count = len(reader.pages)
        if page_count < 1:
            raise ConversionError("PDF không có trang để chuyển sang Word.", IssueCode.UNREADABLE)
        raw_text_len = sum(len((p.extract_text() or "").strip()) for p in reader.pages)
    except ConversionError:
        raise
    except (OSError, PdfReadError, ValueError) as exc:
        raise ConversionError("Không đọc được tệp PDF nguồn.", IssueCode.UNREADABLE) from exc

    working_pdf = pdf_path
    temp_dir_obj: tempfile.TemporaryDirectory | None = None
    try:
        if raw_text_len == 0 and ocr_processor is not None:
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="pdf2docx-ocr-")
            ocr_out = Path(temp_dir_obj.name) / "ocr.pdf"
            ocr_res = ocr_processor.process(pdf_path, ocr_out, language=ocr_language)
            working_pdf = ocr_res.pdf_path
            reader = PdfReader(str(working_pdf), strict=False)

        pages_blocks: list[list[_PageBlock]] = []
        preview_blocks: list[dict[str, object]] = []
        table_count = 0
        paragraph_count = 0

        for page_idx, page in enumerate(reader.pages, start=1):
            spans = _extract_page_spans(page)
            blocks = _analyze_page_blocks(spans)
            pages_blocks.append(blocks)
            for block in blocks:
                if block.is_table:
                    table_count += 1
                    preview_blocks.append(
                        {"page": page_idx, "type": "table", "rows": block.rows}
                    )
                else:
                    paragraph_count += 1
                    preview_blocks.append(
                        {
                            "page": page_idx,
                            "type": "paragraph",
                            "text": block.paragraph_text,
                            "heading": block.is_heading,
                        }
                    )

        _write_ooxml_docx(output_docx_path, pages_blocks)
        return WordConversionResult(
            docx_path=output_docx_path,
            page_count=len(reader.pages),
            table_count=table_count,
            paragraph_count=paragraph_count,
            preview_blocks=preview_blocks,
        )
    finally:
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()

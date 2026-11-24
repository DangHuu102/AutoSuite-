"""Convert PDF documents (including scanned PDFs via OCR) to Word (.docx) while preserving tables."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import html
import math
import re
from statistics import median
import tempfile
from typing import Iterable, Sequence
import unicodedata
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .converter import ConversionError
from .models import IssueCode
from .ocr import OCRProcessor

_INVALID_XML_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)
_NUMERIC_CELL_RE = re.compile(
    r"^[\s(]*[-+]?\d[\d.,\s]*(?:%|VND|VNĐ|USD|đ)?[\s)]*$",
    re.IGNORECASE,
)
_SHORT_INDEX_RE = re.compile(r"^(?:STT|TT|No\.?|\d{1,4}|[IVXLCDM]{1,5})$", re.IGNORECASE)
_LIST_PREFIX_RE = re.compile(r"^(?:[-•*–—]|(?:\d+|[a-zA-Z]|[IVXLCDM]+)[.)])$")

# A4 portrait dimensions in dxa (1 pt = 20 dxa)
_A4_WIDTH_DXA = 11906
_A4_HEIGHT_DXA = 16838
_PAGE_MARGIN_DXA = 1134
_PRINTABLE_WIDTH_DXA = _A4_WIDTH_DXA - 2 * _PAGE_MARGIN_DXA  # 9638 dxa
_MAX_PREVIEW_BLOCKS = 300


def _clean_xml_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    return html.escape(_INVALID_XML_CHARS_RE.sub("", normalized), quote=False)


def _normalize_font_family(raw_name: str) -> str:
    low = (raw_name or "").casefold()
    if "segoe" in low:
        return "Segoe UI"
    if any(
        k in low
        for k in (
            "arial",
            "helvetica",
            "liberation sans",
            "liberationsans",
            "calibri",
            "tahoma",
            "roboto",
            "sans",
        )
    ):
        return "Arial"
    return "Times New Roman"


@dataclass(slots=True)
class _TextSpan:
    x: float
    y: float
    text: str
    font_size: float = 11.0
    x1: float = 0.0
    y1: float = 0.0
    bold: bool = False
    italic: bool = False
    font_family: str = "Times New Roman"
    hard_break_before: bool = False


@dataclass(slots=True)
class _PageRules:
    v_lines: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y0, y1)
    h_lines: list[tuple[float, float, float]] = field(default_factory=list)  # (y, x0, x1)


@dataclass(slots=True)
class _PageBlock:
    is_table: bool
    rows: list[list[str]] = field(default_factory=list)
    paragraph_text: str = ""
    is_heading: bool = False
    col_widths_pt: list[float] = field(default_factory=list)
    col_alignments: list[str] = field(default_factory=list)
    has_header_row: bool = False
    font_family: str = "Times New Roman"


@dataclass(slots=True)
class WordConversionResult:
    docx_path: Path
    page_count: int
    table_count: int
    paragraph_count: int
    preview_blocks: list[dict[str, object]] = field(default_factory=list)


def _est_span_x1(span: _TextSpan) -> float:
    if span.x1 > span.x:
        return span.x1
    upper_count = sum(1 for ch in span.text if ch.isupper())
    avg_factor = 0.50 + 0.12 * (upper_count / max(len(span.text), 1))
    return span.x + max(len(span.text) * span.font_size * avg_factor, 4.0)


def _mult_matrix(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    return (
        a[0] * b[0] + a[1] * b[2],
        a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2],
        a[2] * b[1] + a[3] * b[3],
        a[4] * b[0] + a[5] * b[2] + b[4],
        a[4] * b[1] + a[5] * b[3] + b[5],
    )


def _extract_page_spans(page) -> list[_TextSpan]:
    """Fallback pypdf span extractor with CTM multiplication and font inspection."""
    spans: list[_TextSpan] = []

    def _visitor(text: str, cm, tm, font_dict, font_size: float) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        tm_tup = tuple(float(v) for v in tm[:6]) if tm and len(tm) >= 6 else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        cm_tup = tuple(float(v) for v in cm[:6]) if cm and len(cm) >= 6 else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        m = _mult_matrix(tm_tup, cm_tup)
        x = m[4]
        y = m[5]
        scale = math.hypot(m[2], m[3]) or 1.0
        raw_fs = float(font_size) if font_size and font_size > 0 else 11.0
        eff_fs = max(min(raw_fs * scale if raw_fs <= 3.5 or scale != 1.0 else raw_fs, 72.0), 5.5)

        base_font = ""
        if isinstance(font_dict, dict):
            base_font = str(font_dict.get("/BaseFont", ""))
        low_font = base_font.casefold()
        is_bold = any(k in low_font for k in ("bold", "black", "heavy", "demi", "semibold"))
        is_italic = any(k in low_font for k in ("italic", "oblique"))
        ff = _normalize_font_family(base_font)

        spans.append(
            _TextSpan(
                x=x,
                y=y,
                text=cleaned,
                font_size=eff_fs,
                y1=y + eff_fs,
                bold=is_bold,
                italic=is_italic,
                font_family=ff,
            )
        )

    try:
        page.extract_text(visitor_text=_visitor)
    except Exception:
        fallback_text = (page.extract_text() or "").strip()
        for idx, line in enumerate(fallback_text.splitlines()):
            if line.strip():
                spans.append(_TextSpan(x=50.0, y=800.0 - idx * 14.0, text=line.strip()))
    return spans


def _pdfium_char_font_style(textpage, idx: int) -> tuple[bool, bool, str]:
    try:
        flags = ctypes.c_int(0)
        buf_len = pdfium_c.FPDFText_GetFontInfo(textpage, idx, None, 0, ctypes.byref(flags))
        raw_name = ""
        if buf_len > 0:
            buf = ctypes.create_string_buffer(buf_len)
            pdfium_c.FPDFText_GetFontInfo(textpage, idx, buf, buf_len, ctypes.byref(flags))
            raw_name = buf.value.decode("utf-8", errors="ignore")
        low = raw_name.casefold()
        fval = flags.value
        bold = bool(fval & 0x40000) or any(
            k in low for k in ("bold", "black", "heavy", "semibold", "demi")
        )
        italic = bool(fval & 0x40) or any(k in low for k in ("italic", "oblique"))
        return bold, italic, _normalize_font_family(raw_name)
    except Exception:
        return False, False, "Times New Roman"


def _extract_pdfium_rules(page) -> _PageRules:
    v_lines: list[tuple[float, float, float]] = []
    h_lines: list[tuple[float, float, float]] = []
    try:
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_PATH]):
            try:
                fill_mode = ctypes.c_int(0)
                stroke = ctypes.c_int(0)
                if not pdfium_c.FPDFPath_GetDrawMode(obj, ctypes.byref(fill_mode), ctypes.byref(stroke)):
                    continue
                if fill_mode.value == 0 and stroke.value == 0:
                    continue
                left, bottom, right, top = obj.get_bounds()
                w = right - left
                h = top - bottom
                if w < 0 or h < 0:
                    continue
                # Thin vertical stroke or filled rule
                if w <= 3.2 and h >= 10.0:
                    v_lines.append(((left + right) * 0.5, bottom, top))
                # Thin horizontal stroke or filled rule
                elif h <= 3.2 and w >= 18.0:
                    h_lines.append(((bottom + top) * 0.5, left, right))
                # Stroked rectangular cell box
                elif stroke.value != 0 and w >= 18.0 and h >= 10.0:
                    v_lines.append((left, bottom, top))
                    v_lines.append((right, bottom, top))
                    h_lines.append((bottom, left, right))
                    h_lines.append((top, left, right))
            except Exception:
                continue
    except Exception:
        pass
    return _PageRules(v_lines=v_lines, h_lines=h_lines)


def _extract_pdfium_page_layout(doc, page_index: int) -> tuple[list[_TextSpan], _PageRules]:
    """Extract charbox-accurate text spans and visible ruling lines for a single page."""
    page = doc[page_index]
    tp = None
    try:
        rules = _extract_pdfium_rules(page)
        tp = page.get_textpage()
        n_chars = tp.count_chars()
        if n_chars <= 0:
            return [], rules

        spans: list[_TextSpan] = []
        buf_chars: list[str] = []
        cur_x0 = 0.0
        cur_y0 = 0.0
        cur_x1 = 0.0
        cur_y1 = 0.0
        cur_fs = 11.0
        cur_bold = False
        cur_italic = False
        cur_ff = "Times New Roman"
        cur_hard_break = False
        pending_hard_break = False

        def _flush() -> None:
            nonlocal buf_chars, cur_hard_break
            txt = "".join(buf_chars).strip()
            buf_chars = []
            if txt:
                spans.append(
                    _TextSpan(
                        x=cur_x0,
                        y=cur_y0,
                        text=txt,
                        font_size=cur_fs,
                        x1=max(cur_x1, cur_x0 + 1.0),
                        y1=max(cur_y1, cur_y0 + cur_fs * 0.8),
                        bold=cur_bold,
                        italic=cur_italic,
                        font_family=cur_ff,
                        hard_break_before=cur_hard_break,
                    )
                )
            cur_hard_break = False

        raw_tp = tp.raw
        for i in range(n_chars):
            code = pdfium_c.FPDFText_GetUnicode(raw_tp, i)
            if code in (0, 10, 13):  # NUL, LF, CR
                _flush()
                pending_hard_break = True
                continue
            ch = chr(code)
            cl, cb, cr, ct = tp.get_charbox(i, loose=False)
            cw = cr - cl

            # PDFium injects synthetic zero-width spaces at Td/TJ/cell jumps
            if ch.isspace() and cw <= 0.02:
                _flush()
                pending_hard_break = True
                continue

            raw_fs = float(pdfium_c.FPDFText_GetFontSize(raw_tp, i) or 11.0)
            # Check loose box height if font size was scaled by matrix
            if raw_fs <= 2.5:
                ll, lb, lr, lt = tp.get_charbox(i, loose=True)
                raw_fs = max(lt - lb, 9.0)
            fs = max(min(raw_fs, 72.0), 5.5)

            if ch.isspace():
                if buf_chars:
                    # Wide visual space gap breaks into a separate span
                    if cl - cur_x1 > max(0.75 * cur_fs, 5.5) or cw > max(0.95 * cur_fs, 7.0):
                        _flush()
                        pending_hard_break = True
                    elif not buf_chars[-1].isspace():
                        buf_chars.append(" ")
                        cur_x1 = max(cur_x1, cr)
                continue

            bold, italic, ff = _pdfium_char_font_style(raw_tp, i)
            if not buf_chars:
                buf_chars = [ch]
                cur_x0, cur_y0, cur_x1, cur_y1 = cl, cb, cr, ct
                cur_fs = fs
                cur_bold, cur_italic, cur_ff = bold, italic, ff
                cur_hard_break = pending_hard_break
                pending_hard_break = False
                continue

            dy = abs(cb - cur_y0)
            gap = cl - cur_x1
            trailing_space = buf_chars[-1] == " "
            effective_gap = cl - cur_x1
            if (
                dy > max(2.2, 0.38 * cur_fs)
                or gap < -max(1.8, 0.35 * cur_fs)
                or effective_gap > max(0.75 * cur_fs, 5.5)
                or (trailing_space and effective_gap > max(0.35 * cur_fs, 3.2))
                or abs(fs - cur_fs) > 1.2
                or bold != cur_bold
            ):
                _flush()
                buf_chars = [ch]
                cur_x0, cur_y0, cur_x1, cur_y1 = cl, cb, cr, ct
                cur_fs = fs
                cur_bold, cur_italic, cur_ff = bold, italic, ff
                cur_hard_break = True
                pending_hard_break = False
            else:
                buf_chars.append(ch)
                cur_x1 = max(cur_x1, cr)
                cur_y0 = min(cur_y0, cb)
                cur_y1 = max(cur_y1, ct)

        _flush()
        return spans, rules
    finally:
        if tp is not None:
            try:
                tp.close()
            except Exception:
                pass
        try:
            page.close()
        except Exception:
            pass


def _v_rule_between(rules: _PageRules | None, x_left: float, x_right: float, y0: float, y1: float) -> bool:
    if rules is None or not rules.v_lines:
        return False
    lo = x_left - 1.8
    hi = x_right + 1.8
    ymid = (y0 + y1) * 0.5
    for vx, vy0, vy1 in rules.v_lines:
        if lo <= vx <= hi and (vy0 - 2.5) <= ymid <= (vy1 + 2.5):
            return True
    return False


def _group_spans_into_lines(
    spans: Sequence[_TextSpan],
    y_tolerance: float | None = None,
    *,
    rules: _PageRules | None = None,
) -> list[list[_TextSpan]]:
    if not spans:
        return []

    def _ymid(s: _TextSpan) -> float:
        return (s.y + s.y1) * 0.5 if s.y1 > s.y else s.y + s.font_size * 0.4

    sorted_spans = sorted(spans, key=lambda s: (-_ymid(s), s.x))
    lines: list[list[_TextSpan]] = []
    current_line: list[_TextSpan] = [sorted_spans[0]]
    current_ymid = _ymid(sorted_spans[0])
    current_fs = sorted_spans[0].font_size

    for span in sorted_spans[1:]:
        symid = _ymid(span)
        tol = (
            y_tolerance
            if y_tolerance is not None
            else max(2.2, 0.44 * min(current_fs, span.font_size))
        )
        if abs(symid - current_ymid) <= tol:
            n = len(current_line)
            current_ymid = (current_ymid * n + symid) / (n + 1)
            current_fs = max(current_fs, span.font_size)
            current_line.append(span)
        else:
            lines.append(sorted(current_line, key=lambda s: (s.x, _est_span_x1(s))))
            current_line = [span]
            current_ymid = symid
            current_fs = span.font_size
    if current_line:
        lines.append(sorted(current_line, key=lambda s: (s.x, _est_span_x1(s))))

    merged_lines: list[list[_TextSpan]] = []
    for line in lines:
        merged: list[_TextSpan] = [line[0]]
        for span in line[1:]:
            prev = merged[-1]
            prev_x1 = _est_span_x1(prev)
            span_x1 = _est_span_x1(span)
            gap = span.x - prev_x1
            avg_fs = (prev.font_size + span.font_size) * 0.5
            crossed_rule = _v_rule_between(
                rules,
                prev_x1,
                span.x,
                min(prev.y, span.y),
                max(prev.y1 or prev.y + prev.font_size, span.y1 or span.y + span.font_size),
            )
            if crossed_rule:
                merged.append(span)
                continue

            # Kerning/ligature split inside a word -> merge without space
            if gap <= 0.18 * avg_fs and not (span.hard_break_before and gap > 1.2):
                join_sep = "" if gap <= 0.08 * avg_fs else " "
                merged[-1] = _TextSpan(
                    x=prev.x,
                    y=min(prev.y, span.y),
                    text=f"{prev.text}{join_sep}{span.text}".strip(),
                    font_size=max(prev.font_size, span.font_size),
                    x1=max(prev_x1, span_x1),
                    y1=max(prev.y1, span.y1),
                    bold=prev.bold or span.bold,
                    italic=prev.italic and span.italic,
                    font_family=prev.font_family or span.font_family,
                    hard_break_before=prev.hard_break_before,
                )
            elif (
                not span.hard_break_before
                and gap <= max(0.65 * avg_fs, 5.0)
                and abs(prev.font_size - span.font_size) <= 2.5
            ):
                merged[-1] = _TextSpan(
                    x=prev.x,
                    y=min(prev.y, span.y),
                    text=f"{prev.text} {span.text}".strip(),
                    font_size=max(prev.font_size, span.font_size),
                    x1=max(prev_x1, span_x1),
                    y1=max(prev.y1, span.y1),
                    bold=prev.bold and span.bold,
                    italic=prev.italic and span.italic,
                    font_family=prev.font_family or span.font_family,
                    hard_break_before=prev.hard_break_before,
                )
            else:
                merged.append(span)
        merged_lines.append(merged)
    return merged_lines


def _cluster_1d_coords(xs: Sequence[float], tol: float = 3.0) -> list[float]:
    if not xs:
        return []
    sxs = sorted(xs)
    groups: list[list[float]] = [[sxs[0]]]
    for x in sxs[1:]:
        if x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [sum(g) / len(g) for g in groups]


def _compute_column_intervals(
    table_lines: Sequence[Sequence[_TextSpan]],
    rules: _PageRules | None = None,
) -> tuple[list[tuple[float, float]], list[float]]:
    """Return column intervals [(c0, c1), ...] and column boundary cuts [b0, b1, ..., bk]."""
    all_spans = [s for line in table_lines for s in line]
    if not all_spans:
        return [(0.0, 100.0)], [0.0, 100.0]

    min_y = min(s.y for s in all_spans) - 6.0
    max_y = max(s.y1 if s.y1 > s.y else s.y + s.font_size for s in all_spans) + 6.0
    min_x = min(s.x for s in all_spans)
    max_x = max(_est_span_x1(s) for s in all_spans)

    # 1. Check if vector vertical lines cleanly define the table grid
    if rules and rules.v_lines:
        table_h = max(max_y - min_y, 12.0)
        matching_vx = [
            vx
            for vx, vy0, vy1 in rules.v_lines
            if (min(vy1, max_y) - max(vy0, min_y)) >= 0.45 * table_h
            and (min_x - 25.0) <= vx <= (max_x + 25.0)
        ]
        v_cuts = _cluster_1d_coords(matching_vx, tol=3.5)
        if len(v_cuts) >= 3:
            cols = [(v_cuts[i], v_cuts[i + 1]) for i in range(len(v_cuts) - 1) if v_cuts[i + 1] - v_cuts[i] >= 8.0]
            if len(cols) >= 2:
                bounds = [cols[0][0]] + [c[1] for c in cols]
                return cols, bounds

    # 2. Interval-based X-projection respecting same-row hard separation cuts
    same_row_cuts: list[tuple[float, float]] = []
    for line in table_lines:
        if len(line) < 2:
            continue
        for idx in range(len(line) - 1):
            left_end = _est_span_x1(line[idx])
            right_start = line[idx + 1].x
            if right_start >= left_end - 1.5:
                same_row_cuts.append((left_end, right_start))

    intervals = sorted((s.x, _est_span_x1(s)) for s in all_spans)
    cols: list[tuple[float, float]] = [intervals[0]]
    for x0, x1 in intervals[1:]:
        cur_x0, cur_x1 = cols[-1]
        # Never merge across a gap where two cells on the same row were separated
        separated_on_row = any(
            l_end >= cur_x0 - 1.0 and r_start <= x1 + 1.0 and r_start >= cur_x1 - 2.0 and x0 >= l_end - 2.0
            for l_end, r_start in same_row_cuts
        )
        if not separated_on_row and x0 <= cur_x1 - 1.0:
            cols[-1] = (min(cur_x0, x0), max(cur_x1, x1))
        elif not separated_on_row and (x0 - cur_x1) <= 2.5:
            cols[-1] = (min(cur_x0, x0), max(cur_x1, x1))
        else:
            cols.append((x0, x1))

    if len(cols) < 2:
        mid = (min_x + max_x) * 0.5
        cols = [(min_x, mid), (mid, max(max_x, min_x + 20.0))]

    bounds = [cols[0][0]]
    for i in range(len(cols) - 1):
        bounds.append((cols[i][1] + cols[i + 1][0]) * 0.5)
    bounds.append(max(cols[-1][1], bounds[-1] + 12.0))
    return cols, bounds


def _assign_col_index(span: _TextSpan, cols: Sequence[tuple[float, float]], bounds: Sequence[float]) -> int:
    sx0 = span.x
    sx1 = _est_span_x1(span)
    smid = (sx0 + sx1) * 0.5
    for idx in range(len(cols)):
        if bounds[idx] - 1.0 <= smid <= bounds[idx + 1] + 1.0:
            return idx
    # Overlap fallback
    best_idx = 0
    best_score = -1e9
    for idx, (c0, c1) in enumerate(cols):
        overlap = min(sx1, c1) - max(sx0, c0)
        dist = 0.0 if c0 <= smid <= c1 else min(abs(smid - c0), abs(smid - c1))
        score = overlap - dist
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _infer_col_alignments(rows: Sequence[Sequence[str]], col_count: int, has_header: bool) -> list[str]:
    data_rows = rows[1:] if has_header and len(rows) > 1 else rows
    alignments: list[str] = []
    for c in range(col_count):
        non_empty = [r[c].strip() for r in data_rows if c < len(r) and r[c].strip()]
        if not non_empty:
            alignments.append("left")
            continue
        num_count = sum(1 for val in non_empty if _NUMERIC_CELL_RE.match(val))
        hdr = rows[0][c].strip() if rows and c < len(rows[0]) else ""
        if c == 0 and (
            _SHORT_INDEX_RE.match(hdr)
            or (all(len(v) <= 4 and v.isdigit() for v in non_empty))
        ):
            alignments.append("center")
        elif num_count >= max(1, math.ceil(len(non_empty) * 0.6)):
            alignments.append("right")
        else:
            alignments.append("left")
    return alignments


def _build_table_block(
    table_lines: Sequence[Sequence[_TextSpan]],
    rules: _PageRules | None = None,
    *,
    continuation_map: dict[int, list[tuple[int, str]]] | None = None,
) -> _PageBlock:
    cols, bounds = _compute_column_intervals(table_lines, rules)
    col_count = max(len(cols), 2)
    rows: list[list[str]] = []
    ff_counter: dict[str, int] = {}

    for row_idx, line in enumerate(table_lines):
        row_cells = [""] * col_count
        for span in line:
            ff_counter[span.font_family] = ff_counter.get(span.font_family, 0) + len(span.text)
            best_col = _assign_col_index(span, cols, bounds)
            if row_cells[best_col]:
                row_cells[best_col] = f"{row_cells[best_col]} {span.text}".strip()
            else:
                row_cells[best_col] = span.text
        if continuation_map and row_idx in continuation_map:
            for c_idx, extra_txt in continuation_map[row_idx]:
                if 0 <= c_idx < col_count and extra_txt:
                    row_cells[c_idx] = (
                        f"{row_cells[c_idx]}\n{extra_txt}".strip() if row_cells[c_idx] else extra_txt
                    )
        rows.append(row_cells)

    col_widths_pt = [max(bounds[i + 1] - bounds[i], 14.0) for i in range(col_count)]
    first_line = table_lines[0] if table_lines else []
    first_bold = bool(first_line) and sum(1 for s in first_line if s.bold) >= math.ceil(len(first_line) * 0.5)
    first_non_num = bool(rows) and not any(_NUMERIC_CELL_RE.match(c) for c in rows[0] if c.strip())
    later_has_num = len(rows) > 1 and any(
        _NUMERIC_CELL_RE.match(c) for r in rows[1:] for c in r if c.strip()
    )
    has_header = len(rows) > 1 and (first_bold or (first_non_num and later_has_num))
    alignments = _infer_col_alignments(rows, col_count, has_header)
    dominant_ff = max(ff_counter, key=ff_counter.get) if ff_counter else "Times New Roman"

    return _PageBlock(
        is_table=True,
        rows=rows,
        col_widths_pt=col_widths_pt,
        col_alignments=alignments,
        has_header_row=has_header,
        font_family=dominant_ff,
    )


def _is_genuine_single_row_table(line: Sequence[_TextSpan], rules: _PageRules | None) -> bool:
    if len(line) < 2:
        return False
    if _LIST_PREFIX_RE.match(line[0].text.strip()):
        return False
    y0 = min(s.y for s in line)
    y1 = max(s.y1 if s.y1 > s.y else s.y + s.font_size for s in line)
    if any(
        _v_rule_between(rules, _est_span_x1(line[i]), line[i + 1].x, y0, y1)
        for i in range(len(line) - 1)
    ):
        return True
    avg_fs = sum(s.font_size for s in line) / len(line)
    max_gap = max(line[i + 1].x - _est_span_x1(line[i]) for i in range(len(line) - 1))
    has_numeric = any(_NUMERIC_CELL_RE.match(s.text) for s in line)
    return max_gap >= max(0.85 * avg_fs, 6.5) and has_numeric


def _analyze_page_blocks(
    spans: Sequence[_TextSpan],
    rules: _PageRules | None = None,
) -> list[_PageBlock]:
    lines = _group_spans_into_lines(spans, rules=rules)
    if not lines:
        return []

    all_sizes = [s.font_size for line in lines for s in line]
    body_fs = float(median(all_sizes)) if all_sizes else 11.0
    dominant_page_ff = "Times New Roman"
    if spans:
        ff_counts: dict[str, int] = {}
        for s in spans:
            ff_counts[s.font_family] = ff_counts.get(s.font_family, 0) + len(s.text)
        dominant_page_ff = max(ff_counts, key=ff_counts.get)

    blocks: list[_PageBlock] = []
    pending_table_lines: list[list[_TextSpan]] = []
    pending_continuations: dict[int, list[tuple[int, str]]] = {}

    def _line_heading(single_text: str, max_fs: float, all_bold: bool) -> bool:
        if not single_text:
            return False
        if max_fs >= max(body_fs * 1.18, 12.8):
            return True
        if all_bold and len(single_text) <= 120 and not _NUMERIC_CELL_RE.match(single_text):
            return True
        if (
            6 <= len(single_text) <= 95
            and single_text == single_text.upper()
            and any(c.isalpha() for c in single_text)
        ):
            return True
        return False

    def _emit_paragraph_line(line: Sequence[_TextSpan]) -> None:
        text = " ".join(s.text for s in line).strip()
        if not text:
            return
        max_fs = max(s.font_size for s in line)
        all_bold = all(s.bold for s in line)
        ff = line[0].font_family or dominant_page_ff
        is_hd = _line_heading(text, max_fs, all_bold)
        blocks.append(
            _PageBlock(
                is_table=False,
                paragraph_text=text,
                is_heading=is_hd,
                font_family=ff,
            )
        )

    def _flush_table() -> None:
        nonlocal pending_table_lines, pending_continuations
        if not pending_table_lines:
            return
        if len(pending_table_lines) >= 2 or (
            len(pending_table_lines) == 1 and _is_genuine_single_row_table(pending_table_lines[0], rules)
        ):
            blocks.append(
                _build_table_block(
                    pending_table_lines,
                    rules,
                    continuation_map=pending_continuations,
                )
            )
        else:
            for line in pending_table_lines:
                _emit_paragraph_line(line)
        pending_table_lines = []
        pending_continuations = {}

    for line in lines:
        if len(line) >= 2 and not _LIST_PREFIX_RE.match(line[0].text.strip()):
            pending_table_lines.append(line)
            continue

        # Check if a single-span line is a wrapped cell continuation inside an active table
        if len(pending_table_lines) >= 2 and len(line) == 1:
            single = line[0]
            prev_line = pending_table_lines[-1]
            prev_y = min(s.y for s in prev_line)
            prev_fs = max(s.font_size for s in prev_line)
            dy = prev_y - single.y
            is_hd = _line_heading(single.text, single.font_size, single.bold)
            if 0 <= dy <= 1.85 * prev_fs and not is_hd:
                cols, bounds = _compute_column_intervals(pending_table_lines, rules)
                if bounds[0] - 8.0 <= single.x and _est_span_x1(single) <= bounds[-1] + 15.0:
                    col_idx = _assign_col_index(single, cols, bounds)
                    row_idx = len(pending_table_lines) - 1
                    pending_continuations.setdefault(row_idx, []).append((col_idx, single.text))
                    continue

        _flush_table()
        _emit_paragraph_line(line)

    _flush_table()
    return blocks


def _compute_proportional_dxa(
    col_widths_pt: Sequence[float],
    col_count: int,
    table_width_dxa: int = _PRINTABLE_WIDTH_DXA,
) -> list[int]:
    if col_count <= 0:
        return []
    if len(col_widths_pt) != col_count or sum(col_widths_pt) <= 0:
        raw = [1.0] * col_count
    else:
        raw = [max(w, 12.0) for w in col_widths_pt]

    min_floor = min(680, max(360, table_width_dxa // max(col_count * 2, 1)))
    total_raw = sum(raw)
    widths = [max(int(round(table_width_dxa * (w / total_raw))), min_floor) for w in raw]

    diff = sum(widths) - table_width_dxa
    while diff != 0:
        step = -1 if diff > 0 else 1
        candidates = [
            i for i, w in enumerate(widths) if (w > min_floor if diff > 0 else True)
        ] or list(range(col_count))
        target = max(candidates, key=lambda i: widths[i])
        widths[target] += step
        diff += step
    return widths


def _xml_paragraph(
    text: str,
    *,
    bold: bool = False,
    font_size_half_pts: int = 22,
    font_family: str = "Times New Roman",
    align: str = "left",
    space_before: int = 0,
    space_after: int = 120,
) -> str:
    escaped = _clean_xml_text(text)
    ff = _clean_xml_text(font_family or "Times New Roman")
    b_tag = "<w:b/><w:bCs/>" if bold else ""
    jc_tag = f'<w:jc w:val="{align}"/>' if align in ("center", "right", "both") else ""
    return (
        "<w:p>"
        f'<w:pPr><w:spacing w:before="{space_before}" w:after="{space_after}"/>{jc_tag}</w:pPr>'
        "<w:r>"
        "<w:rPr>"
        f'<w:rFonts w:ascii="{ff}" w:hAnsi="{ff}" w:cs="{ff}" w:eastAsia="{ff}"/>'
        f"{b_tag}"
        f'<w:sz w:val="{font_size_half_pts}"/><w:szCs w:val="{font_size_half_pts}"/>'
        '<w:lang w:val="vi-VN" w:eastAsia="vi-VN" w:bidi="vi-VN"/>'
        "</w:rPr>"
        f'<w:t xml:space="preserve">{escaped}</w:t>'
        "</w:r>"
        "</w:p>"
    )


def _xml_table(
    rows: Sequence[Sequence[str]],
    *,
    col_widths_pt: Sequence[float] = (),
    col_alignments: Sequence[str] = (),
    has_header_row: bool | None = None,
    font_family: str = "Times New Roman",
) -> str:
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    col_widths_dxa = _compute_proportional_dxa(col_widths_pt, col_count, _PRINTABLE_WIDTH_DXA)
    total_dxa = sum(col_widths_dxa) or _PRINTABLE_WIDTH_DXA
    grid_cols = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_widths_dxa)
    use_header = (len(rows) > 1) if has_header_row is None else has_header_row

    borders = (
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="7B93B4"/>'
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="7B93B4"/>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="7B93B4"/>'
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="7B93B4"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="C5D4E8"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="C5D4E8"/>'
        "</w:tblBorders>"
    )

    tr_xmls: list[str] = []
    for row_idx, row in enumerate(rows):
        tc_xmls: list[str] = []
        is_header = row_idx == 0 and use_header
        tr_pr = (
            "<w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>"
            if is_header
            else "<w:trPr><w:cantSplit/></w:trPr>"
        )
        shading = '<w:shd w:val="clear" w:color="auto" w:fill="EDF3FF"/>' if is_header else ""
        valign = "center" if is_header else "top"

        for col_idx in range(col_count):
            cell_text = row[col_idx] if col_idx < len(row) else ""
            w_dxa = col_widths_dxa[col_idx]
            align = (
                "center"
                if is_header and col_idx == 0 and len(cell_text) <= 5
                else (
                    col_alignments[col_idx]
                    if not is_header and col_idx < len(col_alignments)
                    else "left"
                )
            )
            sub_lines = cell_text.split("\n") if cell_text else [""]
            cell_p_xml = "".join(
                _xml_paragraph(
                    sub,
                    bold=is_header,
                    font_size_half_pts=21,
                    font_family=font_family,
                    align=align,
                    space_before=20,
                    space_after=24,
                )
                for sub in sub_lines
            )
            tc_xmls.append(
                "<w:tc>"
                f'<w:tcPr><w:tcW w:w="{w_dxa}" w:type="dxa"/><w:vAlign w:val="{valign}"/>{shading}</w:tcPr>'
                f"{cell_p_xml}"
                "</w:tc>"
            )
        tr_xmls.append(f"<w:tr>{tr_pr}" + "".join(tc_xmls) + "</w:tr>")

    return (
        "<w:tbl>"
        "<w:tblPr>"
        f'<w:tblW w:w="{total_dxa}" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        f"{borders}"
        "<w:tblCellMar>"
        '<w:top w:w="60" w:type="dxa"/>'
        '<w:left w:w="108" w:type="dxa"/>'
        '<w:bottom w:w="60" w:type="dxa"/>'
        '<w:right w:w="108" w:type="dxa"/>'
        "</w:tblCellMar>"
        "</w:tblPr>"
        f"<w:tblGrid>{grid_cols}</w:tblGrid>"
        + "".join(tr_xmls)
        + "</w:tbl>"
        '<w:p><w:pPr><w:spacing w:before="0" w:after="80"/></w:pPr></w:p>'
    )


def _write_ooxml_docx(
    output_path: Path,
    pages_blocks: Iterable[Sequence[_PageBlock]],
    *,
    total_pages: int | None = None,
) -> None:
    """Stream OOXML package directly to disk so multi-page PDFs use O(1 page) RAM."""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman"/>
        <w:sz w:val="22"/>
        <w:szCs w:val="22"/>
        <w:lang w:val="vi-VN" w:eastAsia="vi-VN" w:bidi="vi-VN"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
</w:styles>"""

    page_break_xml = (
        '<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr>'
        '<w:r><w:br w:type="page"/></w:r></w:p>'
    ).encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/styles.xml", styles_xml)

        with zf.open("word/document.xml", "w") as doc_stream:
            doc_stream.write(
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:body>"
            )
            wrote_any_page = False
            for page_index, blocks in enumerate(pages_blocks):
                if page_index > 0:
                    doc_stream.write(page_break_xml)
                wrote_any_page = True
                if not blocks:
                    doc_stream.write(_xml_paragraph("").encode("utf-8"))
                for block in blocks:
                    if block.is_table:
                        chunk = _xml_table(
                            block.rows,
                            col_widths_pt=block.col_widths_pt,
                            col_alignments=block.col_alignments,
                            has_header_row=block.has_header_row,
                            font_family=block.font_family,
                        )
                    else:
                        chunk = _xml_paragraph(
                            block.paragraph_text,
                            bold=block.is_heading,
                            font_size_half_pts=26 if block.is_heading else 22,
                            font_family=block.font_family,
                        )
                    doc_stream.write(chunk.encode("utf-8"))

            if not wrote_any_page:
                doc_stream.write(_xml_paragraph("").encode("utf-8"))

            sect_pr = (
                "<w:sectPr>"
                f'<w:pgSz w:w="{_A4_WIDTH_DXA}" w:h="{_A4_HEIGHT_DXA}"/>'
                f'<w:pgMar w:top="{_PAGE_MARGIN_DXA}" w:right="{_PAGE_MARGIN_DXA}" '
                f'w:bottom="{_PAGE_MARGIN_DXA}" w:left="{_PAGE_MARGIN_DXA}"/>'
                "</w:sectPr>"
                "</w:body></w:document>"
            )
            doc_stream.write(sect_pr.encode("utf-8"))


def _pdf_has_extractable_text(pdf_path: Path, reader: PdfReader) -> bool:
    """Short-circuit check on first page containing text characters."""
    doc = None
    try:
        doc = pdfium.PdfDocument(str(pdf_path))
        for idx in range(len(doc)):
            page = doc[idx]
            tp = None
            try:
                tp = page.get_textpage()
                n = tp.count_chars()
                if n > 0:
                    txt = tp.get_text_bounded().strip()
                    if txt:
                        return True
            finally:
                if tp is not None:
                    tp.close()
                page.close()
        return False
    except Exception:
        return any(bool((p.extract_text() or "").strip()) for p in reader.pages)
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


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
        has_text = _pdf_has_extractable_text(pdf_path, reader)
    except ConversionError:
        raise
    except (OSError, PdfReadError, ValueError) as exc:
        raise ConversionError("Không đọc được tệp PDF nguồn.", IssueCode.UNREADABLE) from exc

    working_pdf = pdf_path
    temp_dir_obj: tempfile.TemporaryDirectory | None = None
    pdfium_doc = None
    try:
        if not has_text and ocr_processor is not None:
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="pdf2docx-ocr-")
            ocr_out = Path(temp_dir_obj.name) / "ocr.pdf"
            ocr_res = ocr_processor.process(pdf_path, ocr_out, language=ocr_language)
            working_pdf = ocr_res.pdf_path
            reader = PdfReader(str(working_pdf), strict=False)
            page_count = len(reader.pages)

        try:
            pdfium_doc = pdfium.PdfDocument(str(working_pdf))
        except Exception:
            pdfium_doc = None

        preview_blocks: list[dict[str, object]] = []
        table_count = 0
        paragraph_count = 0

        def _iter_page_blocks() -> Iterable[list[_PageBlock]]:
            nonlocal table_count, paragraph_count
            for page_idx in range(page_count):
                if pdfium_doc is not None and page_idx < len(pdfium_doc):
                    spans, rules = _extract_pdfium_page_layout(pdfium_doc, page_idx)
                else:
                    spans = _extract_page_spans(reader.pages[page_idx])
                    rules = None
                blocks = _analyze_page_blocks(spans, rules=rules)
                for block in blocks:
                    if block.is_table:
                        table_count += 1
                        if len(preview_blocks) < _MAX_PREVIEW_BLOCKS:
                            preview_blocks.append(
                                {"page": page_idx + 1, "type": "table", "rows": block.rows}
                            )
                    else:
                        paragraph_count += 1
                        if len(preview_blocks) < _MAX_PREVIEW_BLOCKS:
                            preview_blocks.append(
                                {
                                    "page": page_idx + 1,
                                    "type": "paragraph",
                                    "text": block.paragraph_text,
                                    "heading": block.is_heading,
                                }
                            )
                yield blocks

        _write_ooxml_docx(output_docx_path, _iter_page_blocks(), total_pages=page_count)
        return WordConversionResult(
            docx_path=output_docx_path,
            page_count=page_count,
            table_count=table_count,
            paragraph_count=paragraph_count,
            preview_blocks=preview_blocks,
        )
    finally:
        if pdfium_doc is not None:
            try:
                pdfium_doc.close()
            except Exception:
                pass
        if temp_dir_obj is not None:
            temp_dir_obj.cleanup()

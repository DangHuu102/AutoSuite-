"""Safe, deterministic PDF naming and collision resolution."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WINDOWS_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_MAX_PDF_FILENAME_LENGTH = 180
_KNOWN_SOURCE_EXTENSIONS = {
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".doc",
    ".xls",
    ".ppt",
    ".docm",
    ".xlsm",
    ".pptm",
    ".gif",
    ".heic",
}


def _clean_stem(value: str, *, max_length: int | None = None) -> str:
    stem = _INVALID_WINDOWS_CHARS.sub("_", value).strip().rstrip(". ")
    if not stem:
        stem = "tai-lieu"
    if stem.upper() in _RESERVED_WINDOWS_STEMS:
        stem = f"_{stem}"
    max_stem_length = max_length if max_length is not None else (_MAX_PDF_FILENAME_LENGTH - len(".pdf"))
    return stem[:max_stem_length].rstrip(". ") or "tai-lieu"


def safe_source_filename(original_name: str, *, max_stem_length: int | None = None) -> str:
    """Return a single safe basename for an uploaded source file."""
    basename = original_name.replace("\\", "/").split("/")[-1]
    suffix = Path(basename).suffix[:16]
    stem = Path(basename).stem
    cleaned = _clean_stem(stem, max_length=max_stem_length)
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{cleaned}{suffix}"


def normalize_pdf_name(raw_name: str) -> str:
    """Normalize a user-edited output name to one safe PDF basename."""
    value = (raw_name or "").strip()
    if "/" in value or "\\" in value:
        raise ValueError("Nhập tên tệp, không nhập đường dẫn thư mục.")
    if value.casefold().endswith(".pdf"):
        stem = value[:-4]
    else:
        suffix = Path(value).suffix
        if suffix and suffix.casefold() in _KNOWN_SOURCE_EXTENSIONS:
            stem = value[: -len(suffix)]
        else:
            stem = value
    return f"{_clean_stem(stem)}.pdf"


def _destination_names(destination: Path) -> set[str]:
    try:
        return {item.name.casefold() for item in destination.iterdir()}
    except OSError:
        return set()


def resolve_unique_pdf_names(
    names: list[str], destination: Path, *, reserved_names: set[str] | None = None
) -> list[str]:
    """Resolve collisions in order, considering existing destination entries."""
    reserved = _destination_names(destination)
    if reserved_names:
        reserved.update(name.casefold() for name in reserved_names)

    results: list[str] = []
    for raw_name in names:
        normalized = normalize_pdf_name(raw_name)
        stem = normalized[:-4]
        candidate = normalized
        serial = 1
        while candidate.casefold() in reserved:
            marker = f" ({serial})"
            candidate = f"{stem[: _MAX_PDF_FILENAME_LENGTH - len(marker) - 4]}{marker}.pdf"
            serial += 1
        reserved.add(candidate.casefold())
        results.append(candidate)
    return results


def propose_output_names(source_names: list[str], destination: Path) -> list[str]:
    """Propose source-basename.pdf names, adding numeric suffixes as needed."""
    candidates: list[str] = []
    for name in source_names:
        basename = name.replace("\\", "/").split("/")[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
        candidates.append(f"{stem}.pdf")
    return resolve_unique_pdf_names(candidates, destination)


def normalize_docx_name(raw_name: str) -> str:
    """Normalize a user-edited output name to one safe Word (.docx) basename."""
    value = (raw_name or "").strip()
    if "/" in value or "\\" in value:
        raise ValueError("Nhập tên tệp, không nhập đường dẫn thư mục.")
    if value.casefold().endswith(".docx"):
        stem = value[:-5]
    else:
        suffix = Path(value).suffix
        if suffix and suffix.casefold() in _KNOWN_SOURCE_EXTENSIONS:
            stem = value[: -len(suffix)]
        else:
            stem = value
    return f"{_clean_stem(stem)}.docx"


def resolve_unique_docx_names(
    names: list[str], destination: Path | None = None, *, reserved_names: set[str] | None = None
) -> list[str]:
    """Resolve collisions for .docx outputs against both batch and destination."""
    reserved = _destination_names(destination) if destination is not None else set()
    if reserved_names:
        reserved.update(name.casefold() for name in reserved_names)

    results: list[str] = []
    for raw_name in names:
        normalized = normalize_docx_name(raw_name)
        stem = normalized[:-5]
        candidate = normalized
        serial = 1
        while candidate.casefold() in reserved:
            marker = f" ({serial})"
            candidate = f"{stem[: _MAX_PDF_FILENAME_LENGTH - len(marker) - 5]}{marker}.docx"
            serial += 1
        reserved.add(candidate.casefold())
        results.append(candidate)
    return results


def propose_docx_output_names(source_names: list[str], destination: Path | None = None) -> list[str]:
    """Propose source-basename.docx names, adding numeric suffixes as needed."""
    candidates: list[str] = []
    for name in source_names:
        basename = name.replace("\\", "/").split("/")[-1]
        stem = basename.rsplit(".", 1)[0] if "." in basename else basename
        candidates.append(f"{stem}.docx")
    return resolve_unique_docx_names(candidates, destination)

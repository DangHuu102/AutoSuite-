"""Temporary file lifecycle and atomic no-overwrite PDF commits."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from .naming import normalize_docx_name, normalize_pdf_name, safe_source_filename
from .models import OutputPdf, OutputStatus

STAGING_ROOT = Path(tempfile.gettempdir()) / "officeflow-staging"
_BATCH_PREFIX = "batch-"
_ORPHAN_CLEANUP_DONE = False
STREAM_CHUNK_BYTES = 65_536


def _remove_readonly(func, path, _exc) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except OSError:
        pass


def _rmtree_force(target: Path) -> None:
    resolved = str(target.resolve())
    if os.name == "nt" and not resolved.startswith("\\\\?\\"):
        if resolved.startswith("\\\\"):
            path_str = f"\\\\?\\UNC\\{resolved.lstrip('\\')}"
        else:
            path_str = f"\\\\?\\{resolved}"
    else:
        path_str = resolved
    shutil.rmtree(path_str, onexc=_remove_readonly)


def cleanup_orphaned_staging(
    max_age_hours: int = 48
) -> int:
    """Remove only old OfficeFlow batch folders; never follow or delete symlinks."""
    if STAGING_ROOT.is_symlink() or not STAGING_ROOT.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 60 * 60
    removed = 0
    for child in STAGING_ROOT.iterdir():
        try:
            if (
                child.name.startswith(_BATCH_PREFIX)
                and not child.is_symlink()
                and child.is_dir()
                and child.stat().st_mtime < cutoff
            ):
                _rmtree_force(child)
                removed += 1
        except OSError:
            continue
    return removed


def cleanup_orphaned_staging_once(max_age_hours: int = 48) -> int:
    """Run stale-folder cleanup once per app process, before active sessions stage files."""
    global _ORPHAN_CLEANUP_DONE
    if _ORPHAN_CLEANUP_DONE:
        return 0
    removed = cleanup_orphaned_staging(max_age_hours=max_age_hours)
    _ORPHAN_CLEANUP_DONE = True
    return removed


def create_batch_staging(batch_id: str) -> Path:
    """Create an isolated input/PDF staging directory for one batch."""
    if STAGING_ROOT.is_symlink():
        raise RuntimeError("Thư mục staging gốc không hợp lệ (symlink).")
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    batch_dir = STAGING_ROOT / f"{_BATCH_PREFIX}{batch_id}"
    batch_dir.mkdir(mode=0o700, exist_ok=False)
    (batch_dir / "input").mkdir()
    (batch_dir / "pdf").mkdir()
    return batch_dir


def store_source_bytes(staging_dir: Path, source_id: str, original_name: str, data: bytes) -> Path:
    """Write a selected upload into its unique private staging location."""
    safe_name = safe_source_filename(original_name, max_stem_length=48)
    target = staging_dir / "input" / f"{source_id}-{safe_name}"
    with target.open("xb") as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())
    return target


def store_source_stream(
    staging_dir: Path,
    source_id: str,
    original_name: str,
    file_obj: BinaryIO,
    max_bytes: int | None = None,
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> tuple[Path, int]:
    """Stream an upload in 64 KB chunks straight to isolated staging with size enforcement."""
    if staging_dir.is_symlink():
        raise RuntimeError("Thư mục staging không hợp lệ (symlink).")
    safe_name = safe_source_filename(original_name, max_stem_length=48)
    target = staging_dir / "input" / f"{source_id}-{safe_name}"
    written = 0
    if hasattr(file_obj, "seekable") and callable(file_obj.seekable):
        try:
            if file_obj.seekable():
                file_obj.seek(0)
        except OSError:
            pass
    try:
        with target.open("xb") as destination:
            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise OverflowError(
                        f"Tệp '{original_name}' vượt quá giới hạn dung lượng cho phép."
                    )
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        return target, written
    except BaseException:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def source_output_dir(staging_dir: Path, source_id: str) -> Path:
    output_dir = staging_dir / "pdf" / source_id
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def cleanup_batch_staging(staging_dir: Path | None) -> None:
    """Delete a staging directory only when it is a direct managed child."""
    if staging_dir is None or staging_dir.is_symlink():
        return
    try:
        root = STAGING_ROOT.resolve(strict=False)
        target = staging_dir.resolve(strict=False)
        if target.parent == root and target.name.startswith(_BATCH_PREFIX):
            _rmtree_force(target)
    except OSError:
        return


def commit_staged_pdf(output: OutputPdf, destination: Path, final_name: str) -> Path:
    """Copy a staged PDF through a same-volume temporary file, then publish atomically.

    Windows ``os.rename`` refuses to replace an existing destination. POSIX uses a
    hard-link operation with the same exclusive-create property.
    """
    if output.staging_path is None or not output.staging_path.is_file():
        raise FileNotFoundError("Không tìm thấy PDF tạm để lưu.")
    destination_dir = destination.resolve(strict=True)
    if not destination_dir.is_dir():
        raise NotADirectoryError("Thư mục đích không hợp lệ.")
    is_docx = (
        final_name.strip().casefold().endswith(".docx")
        or output.staging_path.suffix.casefold() == ".docx"
    )
    safe_name = normalize_docx_name(final_name) if is_docx else normalize_pdf_name(final_name)
    final_path = destination_dir / safe_name
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".officeflow-", suffix=".tmp", dir=destination_dir, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            with output.staging_path.open("rb") as source_file:
                shutil.copyfileobj(source_file, temp_file, length=1024 * 1024)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        if os.name == "nt":
            os.rename(temp_path, final_path)
            temp_path = None
        else:
            os.link(temp_path, final_path)
        output.status = OutputStatus.COMMITTED
        output.final_name = safe_name
        output.destination_path = final_path
        return final_path
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

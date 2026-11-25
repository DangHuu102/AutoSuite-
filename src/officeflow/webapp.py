"""Ultra-lightweight Starlette + Uvicorn web backend for AutoSuite (< 45 MB idle RAM).

Design principles:
- Lazy-import heavy conversion/PDF modules inside worker threads so idle server boot stays ~30 MB RSS.
- Stream multipart uploads in 64 KB chunks directly to isolated temp staging (never buffer full files in RAM).
- Stream downloads via native HTTP FileResponse (`Content-Disposition: attachment` + `Accept-Ranges: bytes`)
  so browsers trigger their native top-right Download bar at 0 ms latency and 0 MB JS heap, identical to
  top-tier MP4/MP3/video downloaders and document converters (Cobalt, Y2Mate, iLovePDF, Convertio).
- Never scan, query, or expose server-side host user directories (`C:\\Users\\...`).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import ctypes
from dataclasses import dataclass, field
import gc
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, AsyncIterator, Literal
import unicodedata
import urllib.parse
import zipfile

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).with_name("static")
_HEX_ID_RE = re.compile(r"^[a-f0-9]{32}$")

_MAX_FILES = 20
_MAX_SINGLE_BYTES = 100 * 1024 * 1024
_MAX_BATCH_BYTES = 500 * 1024 * 1024
_MAX_MULTIPART_OVERHEAD = 4 * 1024 * 1024

_DEFAULT_LOCAL_HOSTS = frozenset(
    {"127.0.0.1", "localhost", "autosuite.localhost", "::1", "[::1]"}
)

_MIME_PDF = "application/pdf"
_MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _trim_process_memory() -> None:
    """Run Python GC and return unused heap pages to the OS where supported."""
    gc.collect()
    if os.name == "nt":
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetProcessWorkingSetSize(
                handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1)
            )
        except Exception:
            pass
    else:
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def build_content_disposition(
    disposition: Literal["attachment", "inline"], filename: str
) -> str:
    """Build RFC 6266 + RFC 5987 dual Content-Disposition header for Vietnamese UTF-8 names."""
    clean_utf8 = (
        (filename or "tai-lieu.pdf")
        .replace("\r", "")
        .replace("\n", "")
        .replace("\x00", "")
        .strip()
    )
    ascii_fallback = (
        unicodedata.normalize("NFKD", clean_utf8)
        .encode("ascii", "ignore")
        .decode("ascii")
        .replace('"', "")
        .replace("\\", "_")
        .replace(";", "_")
        .strip()
    )
    if not ascii_fallback or ascii_fallback.startswith("."):
        ext = Path(clean_utf8).suffix or ".pdf"
        ascii_fallback = f"autosuite-file{ext}"
    quoted_utf8 = urllib.parse.quote(clean_utf8, safe="-_.~")
    return f'{disposition}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted_utf8}'


def _allowed_hosts() -> set[str]:
    raw = os.environ.get("OFFICEFLOW_ALLOWED_HOSTS", "").strip()
    if raw == "*":
        return {"*"}
    extra = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return set(_DEFAULT_LOCAL_HOSTS) | extra


def _extract_hostname(netloc: str) -> str:
    value = (netloc or "").strip().lower()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[: end + 1] if end != -1 else value
    return value.split(":", 1)[0]


class LocalOriginMiddleware(BaseHTTPMiddleware):
    """Protect local AutoSuite server against DNS rebinding and cross-site CSRF."""

    async def dispatch(self, request: Request, call_next):
        allowed = _allowed_hosts()
        host_header = request.headers.get("host", "").strip()
        req_hostname = _extract_hostname(host_header)

        if "*" not in allowed and req_hostname not in allowed:
            return JSONResponse(
                {"error": "Truy cập bị từ chối: Host không hợp lệ."}, status_code=403
            )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            sec_site = request.headers.get("sec-fetch-site", "").strip().lower()
            if sec_site == "cross-site":
                return JSONResponse(
                    {"error": "Truy cập chéo trang (CSRF) bị từ chối."}, status_code=403
                )
            origin = request.headers.get("origin", "").strip()
            if origin:
                if origin.lower() == "null":
                    return JSONResponse(
                        {"error": "Origin không hợp lệ."}, status_code=403
                    )
                parsed = urllib.parse.urlsplit(origin)
                origin_host = _extract_hostname(parsed.netloc)
                if parsed.scheme not in {"http", "https"}:
                    return JSONResponse(
                        {"error": "Origin scheme không hợp lệ."}, status_code=403
                    )
                if "*" in allowed:
                    if parsed.netloc.lower() != host_header.lower():
                        return JSONResponse(
                            {"error": "Origin không khớp với Host."}, status_code=403
                        )
                elif origin_host not in allowed:
                    return JSONResponse(
                        {"error": "Origin không nằm trong danh sách tin cậy."},
                        status_code=403,
                    )

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response


_auth_service: Any = None
_auth_service_lock = threading.Lock()


def _get_auth_service():
    global _auth_service
    if _auth_service is None:
        with _auth_service_lock:
            if _auth_service is None:
                from .auth import AuthService

                _auth_service = AuthService()
    return _auth_service


def _is_https_request(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").strip().lower()
    return request.url.scheme == "https" or proto == "https"


def _set_auth_cookie(response: Response, request: Request, token: str, max_age: int) -> None:
    from .auth import COOKIE_NAME

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_https_request(request),
    )


def _clear_auth_cookie(response: Response, request: Request) -> None:
    from .auth import COOKIE_NAME

    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_https_request(request),
    )


class AuthCookieMiddleware(BaseHTTPMiddleware):
    """Cookie-based Authentication & Sliding Expiration middleware."""

    async def dispatch(self, request: Request, call_next):
        request.state.user = None
        refreshed: tuple[str, int] | None = None
        cookie_val = request.cookies.get("autosuite_session")
        if cookie_val:
            auth_svc = _get_auth_service()
            user, refreshed = await run_in_threadpool(auth_svc.authenticate_cookie, cookie_val)
            request.state.user = user

        response = await call_next(request)
        if refreshed is not None and "set-cookie" not in {k.lower() for k in response.headers.keys()}:
            token, max_age = refreshed
            _set_auth_cookie(response, request, token, max_age)
        return response


@dataclass(slots=True)
class JobRecord:
    job: Any  # officeflow.models.BatchJob
    created_mono: float
    last_accessed: float
    user_id: int | None = None
    started_mono: float = 0.0
    finished_mono: float = 0.0
    status: str = "queued"  # queued | converting | review | failed | cancelled
    cancelled: bool = False
    progress_completed: int = 0
    progress_total: int = 0
    progress_current_file: str = ""
    error_message: str | None = None
    selected_ids: set[str] = field(default_factory=set)
    edited_names: dict[str, str] = field(default_factory=dict)
    ai_provider: str = ""
    ai_model: str = ""
    ai_filter_request: str = ""
    ai_suggestions: dict[str, Any] = field(default_factory=dict)
    ai_errors: dict[str, str] = field(default_factory=dict)
    version: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)


class BoundedJobStore:
    """LRU + TTL bounded job store that cleans staging directories immediately on eviction."""

    def __init__(self, max_jobs: int = 8, ttl_seconds: float = 1800.0) -> None:
        self.max_jobs = max_jobs
        self.ttl_seconds = ttl_seconds
        self._jobs: OrderedDict[str, JobRecord] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, job_id: str) -> JobRecord | None:
        if not _HEX_ID_RE.match(job_id or ""):
            return None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            record.last_accessed = time.monotonic()
            self._jobs.move_to_end(job_id)
            return record

    def put(self, record: JobRecord) -> bool:
        evicted: list[JobRecord] = []
        now = time.monotonic()
        with self._lock:
            for jid, rec in list(self._jobs.items()):
                if (
                    rec.status not in {"queued", "converting"}
                    and (now - rec.last_accessed) > self.ttl_seconds
                ):
                    evicted.append(self._jobs.pop(jid))

            while len(self._jobs) >= self.max_jobs:
                victim_id = next(
                    (
                        jid
                        for jid, rec in self._jobs.items()
                        if rec.status not in {"queued", "converting"}
                    ),
                    None,
                )
                if victim_id is None:
                    break
                evicted.append(self._jobs.pop(victim_id))

            if len(self._jobs) >= self.max_jobs:
                accepted = False
            else:
                self._jobs[record.job.batch_id] = record
                accepted = True

        if evicted:
            self._finalize_eviction(evicted)
        return accepted

    def pop(self, job_id: str) -> JobRecord | None:
        if not _HEX_ID_RE.match(job_id or ""):
            return None
        with self._lock:
            record = self._jobs.pop(job_id, None)
        if record is not None:
            self._finalize_eviction([record])
        return record

    def cancel_or_pop(self, job_id: str) -> bool:
        """Immediately remove finished jobs; defer staging deletion for active workers."""
        if not _HEX_ID_RE.match(job_id or ""):
            return False
        record_to_evict: JobRecord | None = None
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return False
            with record.lock:
                if record.status in {"queued", "converting"}:
                    record.cancelled = True
                    record.status = "cancelled"
                    record.version += 1
                    return True
            record_to_evict = self._jobs.pop(job_id, None)
        if record_to_evict is not None:
            self._finalize_eviction([record_to_evict])
        return True

    def evict_expired(self) -> int:
        now = time.monotonic()
        evicted: list[JobRecord] = []
        with self._lock:
            for jid, rec in list(self._jobs.items()):
                if (
                    rec.status not in {"queued", "converting"}
                    and (now - rec.last_accessed) > self.ttl_seconds
                ):
                    evicted.append(self._jobs.pop(jid))
        if evicted:
            self._finalize_eviction(evicted)
        return len(evicted)

    def clear_all(self) -> None:
        with self._lock:
            all_records = list(self._jobs.values())
            self._jobs.clear()
        if all_records:
            self._finalize_eviction(all_records)

    @staticmethod
    def _finalize_eviction(records: list[JobRecord]) -> None:
        from .staging import cleanup_batch_staging

        for rec in records:
            try:
                cleanup_batch_staging(rec.job.staging_dir)
                rec.job.staging_dir = None
                rec.job.outputs.clear()
                rec.job.sources.clear()
                rec.ai_suggestions.clear()
            except Exception:
                pass
        _trim_process_memory()


_store = BoundedJobStore(max_jobs=8, ttl_seconds=1800.0)
_convert_executor: ThreadPoolExecutor | None = None
_ai_executor: ThreadPoolExecutor | None = None


def _get_convert_executor() -> ThreadPoolExecutor:
    global _convert_executor
    if _convert_executor is None:
        _convert_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="autosuite-convert"
        )
    return _convert_executor


def _get_ai_executor() -> ThreadPoolExecutor:
    global _ai_executor
    if _ai_executor is None:
        _ai_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="autosuite-ai"
        )
    return _ai_executor


@asynccontextmanager
async def _lifespan(_app: Starlette) -> AsyncIterator[None]:
    from .staging import cleanup_orphaned_staging_once

    await run_in_threadpool(cleanup_orphaned_staging_once)

    async def _sweeper() -> None:
        while True:
            await asyncio.sleep(60.0)
            await run_in_threadpool(_store.evict_expired)

    sweeper_task = asyncio.create_task(_sweeper())
    try:
        yield
    finally:
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass
        global _convert_executor, _ai_executor
        if _convert_executor is not None:
            _convert_executor.shutdown(wait=False, cancel_futures=True)
            _convert_executor = None
        if _ai_executor is not None:
            _ai_executor.shutdown(wait=False, cancel_futures=True)
            _ai_executor = None
        await run_in_threadpool(_store.clear_all)


def _normalize_for_job(job: Any, raw_name: str) -> str:
    from .naming import normalize_docx_name, normalize_pdf_name

    if job.target_format == "docx":
        return normalize_docx_name(raw_name)
    return normalize_pdf_name(raw_name)


def _resolve_unique_names(job: Any, names: list[str]) -> list[str]:
    from .naming import normalize_pdf_name, resolve_unique_docx_names

    if job.target_format == "docx":
        return resolve_unique_docx_names(names, None)
    reserved: set[str] = set()
    results: list[str] = []
    for raw in names:
        normalized = normalize_pdf_name(raw)
        stem = normalized[:-4]
        candidate = normalized
        serial = 1
        while candidate.casefold() in reserved:
            candidate = f"{stem} ({serial}).pdf"
            serial += 1
        reserved.add(candidate.casefold())
        results.append(candidate)
    return results


def _safe_staged_output_path(job: Any, output: Any) -> Path | None:
    """Verify output file exists, is not a symlink, and resides strictly inside job.staging_dir."""
    staging_dir = job.staging_dir
    out_path = output.staging_path
    if staging_dir is None or out_path is None:
        return None
    if staging_dir.is_symlink() or out_path.is_symlink():
        return None
    try:
        resolved_root = staging_dir.resolve(strict=True)
        resolved_file = out_path.resolve(strict=True)
        if not resolved_file.is_relative_to(resolved_root):
            return None
        if not resolved_file.is_file():
            return None
        return resolved_file
    except OSError:
        return None


def _source_label_for_output(job: Any, output: Any) -> str:
    ids = output.related_source_ids
    by_id = {s.source_id: s for s in job.sources}
    if len(ids) > 1:
        names = [by_id[sid].original_name for sid in ids if sid in by_id]
        preview = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        return f"Ảnh ghép ({len(ids)} tệp: {preview})" if preview else f"Ảnh ghép ({len(ids)} tệp)"
    src = by_id.get(output.source_id)
    return src.original_name if src is not None else "Tệp nguồn"


def _serialize_job(record: JobRecord) -> dict[str, Any]:
    with record.lock:
        job = record.job
        elapsed = 0.0
        if record.started_mono > 0:
            end_t = record.finished_mono if record.finished_mono > 0 else time.monotonic()
            elapsed = round(max(end_t - record.started_mono, 0.05), 2)

        sources_payload = [
            {
                "source_id": s.source_id,
                "original_name": s.original_name,
                "extension": s.extension,
                "byte_size": s.byte_size,
                "status": s.status.value,
                "proposed_output_name": s.proposed_output_name,
                "issues": [
                    {
                        "code": iss.issue_code.value,
                        "severity": iss.severity,
                        "message_vi": iss.message_vi,
                    }
                    for iss in s.issues
                ],
            }
            for s in job.sources
        ]

        outputs_payload = []
        for out in job.outputs:
            staged_file = _safe_staged_output_path(job, out)
            byte_size = staged_file.stat().st_size if staged_file is not None else 0
            final_name = record.edited_names.get(out.output_id, out.final_name)
            ai_sug = record.ai_suggestions.get(out.output_id)
            outputs_payload.append(
                {
                    "output_id": out.output_id,
                    "source_id": out.source_id,
                    "source_label": _source_label_for_output(job, out),
                    "proposed_name": out.proposed_name,
                    "final_name": final_name,
                    "selected": out.output_id in record.selected_ids,
                    "byte_size": byte_size,
                    "page_count": out.page_count or 1,
                    "searchable_text": out.searchable_text,
                    "table_count": out.table_count or 0,
                    "has_preview_blocks": bool(out.preview_blocks),
                    "issues": [
                        {
                            "code": iss.issue_code.value,
                            "severity": iss.severity,
                            "message_vi": iss.message_vi,
                        }
                        for iss in out.issues
                    ],
                    "ai_suggestion": (
                        {
                            "decision": ai_sug.decision,
                            "category": ai_sug.category,
                            "suggested_basename": ai_sug.suggested_basename,
                            "reason": ai_sug.reason,
                        }
                        if ai_sug is not None
                        else None
                    ),
                    "ai_error": record.ai_errors.get(out.output_id),
                }
            )

        pct = 100
        if record.status == "queued":
            pct = 5
        elif record.status == "converting":
            if record.progress_total > 0:
                pct = min(96, max(10, int((record.progress_completed / record.progress_total) * 90) + 8))
            else:
                pct = 25

        return {
            "job_id": job.batch_id,
            "status": record.status,
            "target_format": job.target_format,
            "ocr_language": job.ocr_language,
            "merge_images": job.merge_images,
            "merged_pdf_name": job.merged_pdf_name,
            "progress": {
                "completed": record.progress_completed,
                "total": record.progress_total,
                "current_file": record.progress_current_file,
                "percent": pct,
            },
            "elapsed_seconds": elapsed,
            "error_message": record.error_message,
            "sources": sources_payload,
            "outputs": outputs_payload,
            "version": record.version,
        }


def _run_conversion_worker(record: JobRecord) -> None:
    from .batch import convert_batch
    from .converter import LibreOfficeConverter, find_libreoffice
    from .models import BatchState, SourceStatus
    from .ocr import OCRProcessor, find_ocrmypdf
    from .validation import IMAGE_EXTENSIONS, OFFICE_EXTENSIONS

    job = record.job
    try:
        valid_sources = [s for s in job.sources if s.status is SourceStatus.VALID]
        with record.lock:
            if record.cancelled:
                return
            record.started_mono = time.monotonic()
            record.last_accessed = record.started_mono
            if not valid_sources:
                job.state = BatchState.REVIEW
                record.status = "review"
                record.finished_mono = time.monotonic()
                record.version += 1
                return
            record.status = "converting"
            record.progress_total = len(valid_sources)
            record.progress_completed = 0
            record.progress_current_file = valid_sources[0].original_name
            record.version += 1

        is_docx = job.target_format == "docx"
        need_office = not is_docx and any(s.extension in OFFICE_EXTENSIONS for s in valid_sources)
        need_ocr = is_docx or any(
            s.extension == ".pdf" or s.extension in IMAGE_EXTENSIONS for s in valid_sources
        )
        lo_exe = find_libreoffice() if need_office else None
        ocr_exe = find_ocrmypdf() if need_ocr else None
        converter = LibreOfficeConverter(executable=lo_exe) if lo_exe else None
        ocr_proc = OCRProcessor(executable=ocr_exe) if ocr_exe else None

        def _on_progress(completed: int, total: int, source: Any) -> None:
            now = time.monotonic()
            with record.lock:
                record.progress_completed = completed
                record.progress_total = total
                record.progress_current_file = source.original_name
                record.last_accessed = now
                record.version += 1

        convert_batch(job, converter, ocr_proc, _on_progress)

        with record.lock:
            if not record.cancelled:
                record.selected_ids = {out.output_id for out in job.outputs}
                record.edited_names = {out.output_id: out.final_name for out in job.outputs}
                record.progress_completed = record.progress_total
                record.status = "review"
                record.finished_mono = time.monotonic()
                record.last_accessed = record.finished_mono
                record.version += 1

        # Persist personal conversion history for signed-in users
        if not record.cancelled and record.user_id is not None and job.outputs:
            try:
                names_preview = ", ".join(o.final_name for o in job.outputs[:3])
                if len(job.outputs) > 3:
                    names_preview += f" (+{len(job.outputs) - 3})"
                total_out_bytes = sum(
                    sp.stat().st_size
                    for o in job.outputs
                    if (sp := _safe_staged_output_path(job, o)) is not None
                )
                _get_auth_service().repo.add_history(
                    user_id=record.user_id,
                    job_id=job.batch_id,
                    target_format=job.target_format,
                    file_count=len(job.outputs),
                    summary_names=names_preview or "tai-lieu",
                    total_bytes=total_out_bytes,
                )
            except Exception:
                pass
    except Exception as exc:
        with record.lock:
            if not record.cancelled:
                record.status = "failed"
                record.error_message = str(exc) or "Đã xảy ra lỗi khi chuyển đổi tài liệu."
                record.finished_mono = time.monotonic()
                record.version += 1
    finally:
        if record.cancelled:
            _store.pop(job.batch_id)
        else:
            _trim_process_memory()


async def index_page(_request: Request) -> Response:
    index_file = STATIC_DIR / "index.html"
    return FileResponse(
        index_file,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


async def health_check(_request: Request) -> Response:
    return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})


async def api_capabilities(_request: Request) -> Response:
    from .ocr import SUPPORTED_OCR_LANGUAGES
    from .validation import IMAGE_EXTENSIONS, OFFICE_EXTENSIONS, REJECTED_EXTENSIONS

    return JSONResponse(
        {
            "max_files_per_batch": _MAX_FILES,
            "max_single_file_bytes": _MAX_SINGLE_BYTES,
            "max_batch_bytes": _MAX_BATCH_BYTES,
            "office_extensions": sorted(OFFICE_EXTENSIONS),
            "image_extensions": sorted(IMAGE_EXTENSIONS),
            "rejected_extensions": sorted(REJECTED_EXTENSIONS),
            "ocr_languages": list(SUPPORTED_OCR_LANGUAGES),
            "openai_key_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        },
        headers={"Cache-Control": "no-store"},
    )


async def api_create_job(request: Request) -> Response:
    if os.environ.get("OFFICEFLOW_REQUIRE_AUTH", "").strip() in {"1", "true", "yes"}:
        if getattr(request.state, "user", None) is None:
            return JSONResponse(
                {"error": "Vui lòng đăng nhập để sử dụng chức năng chuyển đổi."},
                status_code=401,
            )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > (_MAX_BATCH_BYTES + _MAX_MULTIPART_OVERHEAD):
                return JSONResponse(
                    {
                        "error": "Tổng dung lượng mỗi lô tối đa 500 MB. Hãy chia thành nhiều lô nhỏ hơn."
                    },
                    status_code=413,
                )
        except ValueError:
            pass

    from .batch import create_batch_job
    from .staging import cleanup_batch_staging

    try:
        async with request.form(
            max_files=_MAX_FILES,
            max_fields=32,
            max_part_size=65_536,
        ) as form:
            uploads = [item for item in form.getlist("files") if hasattr(item, "read")]
            if not uploads:
                return JSONResponse({"error": "Hãy chọn ít nhất một tệp."}, status_code=400)

            target_format = str(form.get("target_format") or "pdf").strip().lower()
            ocr_language = str(form.get("ocr_language") or "vie").strip()
            merge_raw = str(form.get("merge_images") or "false").strip().lower()
            merge_images = merge_raw in {"1", "true", "yes", "on"}
            merged_pdf_name = str(form.get("merged_pdf_name") or "Anh-gop.pdf").strip() or "Anh-gop.pdf"

            def _stage_sync():
                return create_batch_job(
                    uploads,
                    None,
                    ocr_language=ocr_language,
                    merge_images=merge_images,
                    merged_pdf_name=merged_pdf_name,
                    target_format=target_format,
                )

            try:
                job = await run_in_threadpool(_stage_sync)
            finally:
                for up in uploads:
                    close_fn = getattr(up, "close", None)
                    if callable(close_fn):
                        try:
                            res = close_fn()
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        msg = str(exc)
        if "Too many files" in msg or "maximum number of files" in msg.lower():
            return JSONResponse(
                {"error": f"Mỗi lô nhận tối đa {_MAX_FILES} tệp."}, status_code=400
            )
        return JSONResponse(
            {"error": "Không đọc được dữ liệu tải lên. Hãy kiểm tra lại tệp đã chọn."},
            status_code=400,
        )

    now = time.monotonic()
    current_user = getattr(request.state, "user", None)
    record = JobRecord(
        job=job,
        created_mono=now,
        last_accessed=now,
        user_id=current_user.id if current_user is not None else None,
        status="queued",
    )
    if not _store.put(record):
        await run_in_threadpool(cleanup_batch_staging, job.staging_dir)
        job.staging_dir = None
        return JSONResponse(
            {"error": "Máy chủ đang xử lý tối đa số lô đồng thời. Vui lòng thử lại sau ít giây."},
            status_code=429,
        )

    _get_convert_executor().submit(_run_conversion_worker, record)
    return JSONResponse(_serialize_job(record), status_code=202, headers={"Cache-Control": "no-store"})


async def api_get_job(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    record = _store.get(job_id)
    if record is None:
        return JSONResponse(
            {"error": "Lô chuyển đổi không tồn tại hoặc đã hết hạn dọn dẹp."}, status_code=404
        )
    return JSONResponse(_serialize_job(record), headers={"Cache-Control": "no-store"})


async def api_job_events(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    record = _store.get(job_id)
    if record is None:
        return JSONResponse({"error": "Không tìm thấy lô chuyển đổi."}, status_code=404)

    async def _event_stream() -> AsyncIterator[bytes]:
        last_ver = -1
        ticks = 0
        while True:
            if await request.is_disconnected():
                break
            snapshot = _serialize_job(record)
            cur_ver = snapshot["version"]
            status = snapshot["status"]
            if cur_ver != last_ver:
                last_ver = cur_ver
                if status in {"review", "failed", "cancelled"}:
                    payload = json.dumps(snapshot, ensure_ascii=False)
                    yield f"event: done\ndata: {payload}\n\n".encode("utf-8")
                    break
                payload = json.dumps(snapshot["progress"], ensure_ascii=False)
                yield f"event: progress\ndata: {payload}\n\n".encode("utf-8")
            else:
                ticks += 1
                if ticks % 50 == 0:
                    yield b": keepalive\n\n"
            await asyncio.sleep(0.15)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def api_update_outputs(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    record = _store.get(job_id)
    if record is None:
        return JSONResponse({"error": "Không tìm thấy lô chuyển đổi."}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Dữ liệu JSON không hợp lệ."}, status_code=400)

    names_in = body.get("names")
    selected_in = body.get("selected_ids")

    with record.lock:
        job = record.job
        valid_out_ids = {o.output_id for o in job.outputs}
        if isinstance(selected_in, list):
            record.selected_ids = {str(oid) for oid in selected_in if str(oid) in valid_out_ids}
        if isinstance(names_in, dict):
            temp_names = dict(record.edited_names)
            for oid, raw_name in names_in.items():
                if oid in valid_out_ids and isinstance(raw_name, str):
                    try:
                        temp_names[oid] = _normalize_for_job(job, raw_name)
                    except ValueError as exc:
                        return JSONResponse({"error": str(exc)}, status_code=400)
            ordered_ids = [o.output_id for o in job.outputs]
            unique = _resolve_unique_names(
                job, [temp_names.get(oid, "tai-lieu") for oid in ordered_ids]
            )
            for oid, u_name in zip(ordered_ids, unique, strict=True):
                record.edited_names[oid] = u_name
        record.version += 1

    return JSONResponse(_serialize_job(record), headers={"Cache-Control": "no-store"})


async def api_download_single(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    record = _store.get(job_id)
    if record is None:
        return JSONResponse({"error": "Tệp tải xuống đã hết hạn hoặc không tồn tại."}, status_code=404)

    output_id = (
        request.path_params.get("output_id")
        or request.query_params.get("output_id")
        or ""
    ).strip()
    if not output_id and len(record.job.outputs) == 1:
        output_id = record.job.outputs[0].output_id
    if not _HEX_ID_RE.match(output_id):
        return JSONResponse({"error": "Mã tệp đầu ra không hợp lệ."}, status_code=400)

    output = next((o for o in record.job.outputs if o.output_id == output_id), None)
    if output is None:
        return JSONResponse({"error": "Không tìm thấy tệp đầu ra."}, status_code=404)

    staged_file = _safe_staged_output_path(record.job, output)
    if staged_file is None:
        return JSONResponse({"error": "Tệp tạm không còn khả dụng."}, status_code=404)

    requested_name = (
        request.query_params.get("name")
        or request.query_params.get("filename")
        or record.edited_names.get(output_id)
        or output.final_name
    )
    try:
        safe_name = _normalize_for_job(record.job, requested_name)
    except ValueError:
        safe_name = output.final_name

    with record.lock:
        record.last_accessed = time.monotonic()

    is_docx = record.job.target_format == "docx" or staged_file.suffix.casefold() == ".docx"
    mime = _MIME_DOCX if is_docx else _MIME_PDF
    stat_res = staged_file.stat()

    return FileResponse(
        path=staged_file,
        status_code=200,
        media_type=mime,
        stat_result=stat_res,
        filename=None,
        headers={
            "Content-Disposition": build_content_disposition("attachment", safe_name),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _build_temp_zip(job: Any, items: list[tuple[Path, str]]) -> Path:
    staging_dir = job.staging_dir
    if staging_dir is None or staging_dir.is_symlink():
        raise FileNotFoundError("Vùng tạm không hợp lệ.")
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix=".bundle-", suffix=".zip", dir=staging_dir, delete=False
    ) as tmp:
        zip_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as zf:
            for file_path, arcname in items:
                zf.write(file_path, arcname=arcname)
        return zip_path
    except BaseException:
        _safe_unlink(zip_path)
        raise


async def api_download_zip(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    record = _store.get(job_id)
    if record is None:
        return JSONResponse({"error": "Lô tải xuống không tồn tại hoặc đã hết hạn."}, status_code=404)

    has_ids_param = "ids" in request.query_params
    ids_param = request.query_params.get("ids", "").strip()
    names_param = request.query_params.get("names", "").strip()
    custom_names: dict[str, str] = {}
    if names_param:
        try:
            parsed_names = json.loads(names_param)
            if isinstance(parsed_names, dict):
                custom_names = {str(k): str(v) for k, v in parsed_names.items()}
        except Exception:
            pass

    with record.lock:
        job = record.job
        if has_ids_param:
            wanted = {part.strip() for part in ids_param.split(",") if _HEX_ID_RE.match(part.strip())}
        else:
            wanted = set(record.selected_ids)

        chosen_outputs = [o for o in job.outputs if o.output_id in wanted]
        raw_names: list[str] = []
        staged_paths: list[Path] = []
        for out in chosen_outputs:
            sp = _safe_staged_output_path(job, out)
            if sp is None:
                continue
            candidate_raw = (
                custom_names.get(out.output_id)
                or record.edited_names.get(out.output_id)
                or out.final_name
            )
            try:
                norm = _normalize_for_job(job, candidate_raw)
            except ValueError:
                norm = out.final_name
            staged_paths.append(sp)
            raw_names.append(norm)

        if not staged_paths:
            return JSONResponse({"error": "Không có tệp hợp lệ để nén ZIP."}, status_code=400)
        unique_names = _resolve_unique_names(job, raw_names)
        items = list(zip(staged_paths, unique_names, strict=True))

    try:
        zip_path = await run_in_threadpool(_build_temp_zip, record.job, items)
        stat_res = zip_path.stat()
    except OSError:
        return JSONResponse({"error": "Tệp tạm không còn khả dụng."}, status_code=404)
    zip_label = "AutoSuite-Word.zip" if record.job.target_format == "docx" else "AutoSuite-PDF.zip"

    return FileResponse(
        path=zip_path,
        status_code=200,
        media_type="application/zip",
        stat_result=stat_res,
        filename=None,
        background=BackgroundTask(_safe_unlink, zip_path),
        headers={
            "Content-Disposition": build_content_disposition("attachment", zip_label),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def api_view_output_inline(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    output_id = request.path_params.get("output_id", "")
    record = _store.get(job_id)
    if record is None or not _HEX_ID_RE.match(output_id):
        return JSONResponse({"error": "Không tìm thấy tệp xem trước."}, status_code=404)

    output = next((o for o in record.job.outputs if o.output_id == output_id), None)
    if output is None:
        return JSONResponse({"error": "Không tìm thấy tệp xem trước."}, status_code=404)

    staged_file = _safe_staged_output_path(record.job, output)
    if staged_file is None:
        return JSONResponse({"error": "Tệp xem trước không còn khả dụng."}, status_code=404)

    safe_name = record.edited_names.get(output_id, output.final_name)
    is_docx = record.job.target_format == "docx" or staged_file.suffix.casefold() == ".docx"
    if is_docx:
        return JSONResponse(
            {
                "output_id": output.output_id,
                "final_name": safe_name,
                "page_count": output.page_count or 1,
                "table_count": output.table_count or 0,
                "blocks": output.preview_blocks or [],
            },
            headers={"Cache-Control": "no-store"},
        )

    stat_res = staged_file.stat()
    return FileResponse(
        path=staged_file,
        status_code=200,
        media_type=_MIME_PDF,
        stat_result=stat_res,
        filename=None,
        headers={
            "Content-Disposition": build_content_disposition("inline", safe_name),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


async def api_preview_blocks(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    output_id = request.path_params.get("output_id", "")
    record = _store.get(job_id)
    if record is None or not _HEX_ID_RE.match(output_id):
        return JSONResponse({"error": "Không tìm thấy nội dung xem trước."}, status_code=404)

    output = next((o for o in record.job.outputs if o.output_id == output_id), None)
    if output is None:
        return JSONResponse({"error": "Không tìm thấy nội dung xem trước."}, status_code=404)

    return JSONResponse(
        {
            "output_id": output.output_id,
            "final_name": record.edited_names.get(output_id, output.final_name),
            "page_count": output.page_count or 1,
            "table_count": output.table_count or 0,
            "blocks": output.preview_blocks or [],
        },
        headers={"Cache-Control": "no-store"},
    )


async def api_job_report(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    fmt = request.path_params.get("fmt", "json").lower()
    record = _store.get(job_id)
    if record is None:
        return JSONResponse({"error": "Không tìm thấy lô báo cáo."}, status_code=404)

    from .reporting import build_batch_report, format_report_csv, format_report_json

    with record.lock:
        report = build_batch_report(
            record.job,
            record.ai_suggestions,
            ai_provider=record.ai_provider or None,
            ai_model=record.ai_model or None,
        )
        report["destination"] = "browser-download"

    if fmt == "csv":
        data = format_report_csv(report)
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": build_content_disposition(
                    "attachment", f"autosuite-report-{job_id[:8]}.csv"
                ),
                "Cache-Control": "no-store",
            },
        )
    data = format_report_json(report)
    return Response(
        content=data,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": build_content_disposition(
                "attachment", f"autosuite-report-{job_id[:8]}.json"
            ),
            "Cache-Control": "no-store",
        },
    )


async def api_ai_models(_request: Request) -> Response:
    from .ai_filter import LocalAIError, list_local_models

    loop = asyncio.get_running_loop()

    def _fetch_models() -> tuple[bool, list[str]]:
        try:
            return True, list_local_models()
        except LocalAIError:
            return False, []

    ollama_ok, models = await loop.run_in_executor(_get_ai_executor(), _fetch_models)
    return JSONResponse(
        {
            "ollama_running": ollama_ok,
            "models": models,
            "openai_key_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
            "default_openai_model": os.environ.get("OFFICEFLOW_OPENAI_MODEL", "gpt-4o-mini"),
        },
        headers={"Cache-Control": "no-store"},
    )


async def api_ai_classify(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    record = _store.get(job_id)
    if record is None:
        return JSONResponse({"error": "Không tìm thấy lô chuyển đổi."}, status_code=404)
    if record.job.target_format == "docx":
        return JSONResponse(
            {"error": "Tính năng phân loại PDF chỉ áp dụng cho đầu ra PDF."}, status_code=400
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Dữ liệu JSON không hợp lệ."}, status_code=400)

    provider = str(body.get("provider") or "ollama").strip().lower()
    model = str(body.get("model") or "").strip()
    filter_request = str(body.get("filter_request") or "").strip()
    cloud_consent = bool(body.get("cloud_consent"))

    if provider not in {"ollama", "openai"}:
        return JSONResponse({"error": "Nhà cung cấp AI không hợp lệ."}, status_code=400)
    if not model or not filter_request:
        return JSONResponse({"error": "Hãy nhập tên model và tiêu chí phân loại."}, status_code=400)
    if provider == "openai" and not cloud_consent:
        return JSONResponse(
            {"error": "Cần xác nhận đồng ý gửi trích đoạn PDF tới OpenAI API."}, status_code=400
        )

    from .ai_filter import LocalAIError, classify_pdf_batch

    items: list[tuple[str, Path, str]] = []
    with record.lock:
        for out in record.job.outputs:
            sp = _safe_staged_output_path(record.job, out)
            if sp is not None:
                items.append((out.output_id, sp, _source_label_for_output(record.job, out)))

    if not items:
        return JSONResponse({"error": "Không có tệp PDF hợp lệ để phân loại."}, status_code=400)

    loop = asyncio.get_running_loop()

    def _classify_sync():
        return classify_pdf_batch(
            items,
            provider=provider,
            model=model,
            filter_request=filter_request,
            allow_cloud=cloud_consent,
        )

    try:
        results = await loop.run_in_executor(_get_ai_executor(), _classify_sync)
    except (LocalAIError, ValueError, OSError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    with record.lock:
        record.ai_provider = provider
        record.ai_model = model
        record.ai_filter_request = filter_request
        record.ai_suggestions.clear()
        record.ai_errors.clear()
        for res in results:
            if res.suggestion is not None:
                record.ai_suggestions[res.item_id] = res.suggestion
            elif res.error:
                record.ai_errors[res.item_id] = res.error
        record.version += 1

    return JSONResponse(_serialize_job(record), headers={"Cache-Control": "no-store"})


async def api_delete_job(request: Request) -> Response:
    job_id = request.path_params.get("job_id", "")
    removed = await run_in_threadpool(_store.cancel_or_pop, job_id)
    return JSONResponse({"ok": True, "removed": bool(removed)}, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Authentication, Account & Role-Based Authorization (RBAC) Controllers
# ---------------------------------------------------------------------------


def _require_auth(request: Request) -> tuple[Any, Response | None]:
    user = getattr(request.state, "user", None)
    if user is None:
        return None, JSONResponse(
            {"error": "Vui lòng đăng nhập để truy cập chức năng này."}, status_code=401
        )
    return user, None


def _require_role(request: Request, required_role: str) -> tuple[Any, Response | None]:
    user, err = _require_auth(request)
    if err is not None:
        return None, err
    if user.role != required_role:
        return None, JSONResponse(
            {"error": "Bạn không có quyền truy cập khu vực Quản trị (403 Forbidden)."},
            status_code=403,
        )
    return user, None


async def api_auth_me(request: Request) -> Response:
    user = getattr(request.state, "user", None)
    return JSONResponse(
        {
            "authenticated": user is not None,
            "user": user.to_dict() if user is not None else None,
        },
        headers={"Cache-Control": "no-store"},
    )


async def api_auth_register(request: Request) -> Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Invalid body")
    except Exception:
        return JSONResponse({"error": "Dữ liệu đăng ký không hợp lệ."}, status_code=400)

    from .auth import RegisterInputModel, ValidationError

    try:
        dto = RegisterInputModel.from_dict(body)
        auth_svc = _get_auth_service()
        user_vm, token, ttl = await run_in_threadpool(auth_svc.register, dto)
    except ValidationError as exc:
        return JSONResponse(
            {"error": str(exc), "field_errors": exc.field_errors}, status_code=400
        )

    resp = JSONResponse(
        {"authenticated": True, "user": user_vm.to_dict()},
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )
    _set_auth_cookie(resp, request, token, ttl)
    return resp


async def api_auth_login(request: Request) -> Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Invalid body")
    except Exception:
        return JSONResponse({"error": "Dữ liệu đăng nhập không hợp lệ."}, status_code=400)

    from .auth import LoginInputModel, ValidationError

    client_ip = request.client.host if request.client else "local"
    try:
        dto = LoginInputModel.from_dict(body)
        auth_svc = _get_auth_service()
        user_vm, token, ttl = await run_in_threadpool(auth_svc.login, dto, client_ip)
    except ValidationError as exc:
        status = 429 if "quá nhiều lần" in str(exc).lower() else 401
        return JSONResponse(
            {"error": str(exc), "field_errors": exc.field_errors}, status_code=status
        )

    resp = JSONResponse(
        {"authenticated": True, "user": user_vm.to_dict()},
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )
    _set_auth_cookie(resp, request, token, ttl)
    return resp


async def api_auth_logout(request: Request) -> Response:
    resp = JSONResponse({"ok": True, "authenticated": False}, headers={"Cache-Control": "no-store"})
    _clear_auth_cookie(resp, request)
    return resp


async def api_account_change_password(request: Request) -> Response:
    user, err = _require_auth(request)
    if err is not None:
        return err
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Invalid body")
    except Exception:
        return JSONResponse({"error": "Dữ liệu không hợp lệ."}, status_code=400)

    from .auth import ChangePasswordInputModel, ValidationError

    try:
        dto = ChangePasswordInputModel.from_dict(body)
        auth_svc = _get_auth_service()
        await run_in_threadpool(auth_svc.change_password, user.id, dto)
    except ValidationError as exc:
        return JSONResponse(
            {"error": str(exc), "field_errors": exc.field_errors}, status_code=400
        )

    return JSONResponse({"ok": True, "message": "Đã cập nhật mật khẩu thành công."}, headers={"Cache-Control": "no-store"})


async def api_account_history(request: Request) -> Response:
    user, err = _require_auth(request)
    if err is not None:
        return err
    auth_svc = _get_auth_service()
    rows = await run_in_threadpool(auth_svc.repo.list_history, user.id, 50)
    return JSONResponse(
        {"items": [r.to_dict() for r in rows]},
        headers={"Cache-Control": "no-store"},
    )


async def api_account_delete_history(request: Request) -> Response:
    user, err = _require_auth(request)
    if err is not None:
        return err
    try:
        hid = int(request.path_params.get("history_id", "0"))
    except ValueError:
        return JSONResponse({"error": "Mã lịch sử không hợp lệ."}, status_code=400)
    auth_svc = _get_auth_service()
    deleted = await run_in_threadpool(auth_svc.repo.delete_history_item, user.id, hid)
    return JSONResponse({"ok": True, "deleted": deleted}, headers={"Cache-Control": "no-store"})


async def api_admin_list_users(request: Request) -> Response:
    _admin, err = _require_role(request, "Admin")
    if err is not None:
        return err
    from .auth import UserViewModel

    auth_svc = _get_auth_service()
    users = await run_in_threadpool(auth_svc.repo.list_users)
    return JSONResponse(
        {"users": [UserViewModel.from_entity(u).to_dict() for u in users]},
        headers={"Cache-Control": "no-store"},
    )


async def api_admin_update_role(request: Request) -> Response:
    admin, err = _require_role(request, "Admin")
    if err is not None:
        return err
    try:
        target_id = int(request.path_params.get("user_id", "0"))
        body = await request.json()
        new_role = str(body.get("role") or "").strip()
    except Exception:
        return JSONResponse({"error": "Dữ liệu không hợp lệ."}, status_code=400)

    from .auth import ValidationError

    auth_svc = _get_auth_service()
    try:
        updated = await run_in_threadpool(auth_svc.set_user_role, admin.id, target_id, new_role)
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse({"user": updated.to_dict()}, headers={"Cache-Control": "no-store"})


async def api_admin_delete_user(request: Request) -> Response:
    admin, err = _require_role(request, "Admin")
    if err is not None:
        return err
    try:
        target_id = int(request.path_params.get("user_id", "0"))
    except ValueError:
        return JSONResponse({"error": "Mã người dùng không hợp lệ."}, status_code=400)

    from .auth import ValidationError

    auth_svc = _get_auth_service()
    try:
        deleted = await run_in_threadpool(auth_svc.delete_user, admin.id, target_id)
    except ValidationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    return JSONResponse({"ok": True, "deleted": deleted}, headers={"Cache-Control": "no-store"})


routes = [
    Route("/", endpoint=index_page, methods=["GET"]),
    Route("/api/health", endpoint=health_check, methods=["GET"]),
    Route("/_stcore/health", endpoint=health_check, methods=["GET"]),
    Route("/api/capabilities", endpoint=api_capabilities, methods=["GET"]),
    Route("/api/auth/me", endpoint=api_auth_me, methods=["GET"]),
    Route("/api/auth/register", endpoint=api_auth_register, methods=["POST"]),
    Route("/api/auth/login", endpoint=api_auth_login, methods=["POST"]),
    Route("/api/auth/logout", endpoint=api_auth_logout, methods=["POST"]),
    Route("/api/account/password", endpoint=api_account_change_password, methods=["POST"]),
    Route("/api/account/history", endpoint=api_account_history, methods=["GET"]),
    Route("/api/account/history/{history_id}", endpoint=api_account_delete_history, methods=["DELETE"]),
    Route("/api/admin/users", endpoint=api_admin_list_users, methods=["GET"]),
    Route("/api/admin/users/{user_id}/role", endpoint=api_admin_update_role, methods=["PATCH"]),
    Route("/api/admin/users/{user_id}", endpoint=api_admin_delete_user, methods=["DELETE"]),
    Route("/api/jobs", endpoint=api_create_job, methods=["POST"]),
    Route("/api/jobs/{job_id}", endpoint=api_get_job, methods=["GET"]),
    Route("/api/jobs/{job_id}", endpoint=api_delete_job, methods=["DELETE"]),
    Route("/api/jobs/{job_id}/events", endpoint=api_job_events, methods=["GET"]),
    Route("/api/jobs/{job_id}/outputs", endpoint=api_update_outputs, methods=["PATCH"]),
    Route("/api/jobs/{job_id}/download", endpoint=api_download_single, methods=["GET"]),
    Route(
        "/api/jobs/{job_id}/outputs/{output_id}/download",
        endpoint=api_download_single,
        methods=["GET"],
    ),
    Route("/api/jobs/{job_id}/download-zip", endpoint=api_download_zip, methods=["GET"]),
    Route("/api/jobs/{job_id}/download-all.zip", endpoint=api_download_zip, methods=["GET"]),
    Route(
        "/api/jobs/{job_id}/outputs/{output_id}/view",
        endpoint=api_view_output_inline,
        methods=["GET"],
    ),
    Route(
        "/api/jobs/{job_id}/outputs/{output_id}/preview",
        endpoint=api_view_output_inline,
        methods=["GET"],
    ),
    Route(
        "/api/jobs/{job_id}/outputs/{output_id}/preview-blocks",
        endpoint=api_preview_blocks,
        methods=["GET"],
    ),
    Route("/api/jobs/{job_id}/report.{fmt}", endpoint=api_job_report, methods=["GET"]),
    Route("/api/ai/models", endpoint=api_ai_models, methods=["GET"]),
    Route("/api/jobs/{job_id}/ai-classify", endpoint=api_ai_classify, methods=["POST"]),
    Mount("/static", app=StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static"),
]

app = Starlette(
    debug=False,
    routes=routes,
    middleware=[Middleware(LocalOriginMiddleware), Middleware(AuthCookieMiddleware)],
    lifespan=_lifespan,
)

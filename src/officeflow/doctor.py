"""Read-only environment diagnostics for OfficeFlow (`officeflow doctor`)."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .ai_filter import LocalAIError, list_local_models
from .converter import find_libreoffice
from .ocr import find_ocrmypdf, find_tesseract, inspect_tessdata
from .staging import STAGING_ROOT


def _libreoffice_version(executable: str) -> str | None:
    version_ini = Path(executable).with_name("version.ini")
    if version_ini.is_file():
        try:
            for line in version_ini.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("UpdateID=") or line.startswith("buildid="):
                    return line.partition("=")[2].strip()
        except OSError:
            pass
    return None


def _package_version(dist_name: str) -> str | None:
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _tesseract_version(executable: Path) -> str | None:
    try:
        proc = subprocess.run(
            [str(executable), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first_line = (proc.stdout or proc.stderr or "").strip().splitlines()
        return first_line[0].strip() if first_line else None
    except Exception:
        return None


def collect_doctor_report() -> dict[str, Any]:
    """Inspect local conversion, OCR, desktop, staging, and AI runtimes without side effects."""
    lo_path = find_libreoffice()
    lo_version = _libreoffice_version(lo_path) if lo_path else None

    ocrmypdf_path = find_ocrmypdf()
    ocrmypdf_version = _package_version("ocrmypdf")

    tesseract_path = find_tesseract()
    tesseract_version = _tesseract_version(tesseract_path) if tesseract_path else None

    tess_info = inspect_tessdata("vie")
    req_langs = tess_info.get("required_languages", {})
    has_vie = bool(req_langs.get("vie"))
    has_eng = bool(req_langs.get("eng"))
    has_osd = bool(req_langs.get("osd"))
    support_ready = bool(tess_info.get("support_files_ready"))
    if tess_info.get("resolved_dir") and has_vie and has_eng and has_osd and support_ready:
        tess_status = "ok"
        tess_msg = "Đầy đủ gói ngôn ngữ (vie, eng, osd) và tệp cấu hình PDF/hOCR."
        tess_hint = None
    elif tess_info.get("resolved_dir") and has_vie:
        tess_status = "warning"
        tess_msg = "Đã có gói tiếng Việt (vie), nhưng thiếu gói phụ trợ hoặc cấu hình."
        tess_hint = "Kiểm tra eng.traineddata, osd.traineddata, configs/hocr và pdf.ttf trong tessdata."
    else:
        tess_status = "missing"
        tess_msg = "Chưa tìm thấy gói ngôn ngữ OCR tiếng Việt (vie.traineddata)."
        tess_hint = "Chép vie.traineddata vào thư mục tessdata hoặc đặt biến TESSDATA_PREFIX."

    webview_installed = importlib.util.find_spec("webview") is not None
    webview_version = _package_version("pywebview") if webview_installed else None

    staging_is_symlink = STAGING_ROOT.is_symlink()
    staging_ok = not staging_is_symlink

    ollama_exe = shutil.which("ollama") or shutil.which("ollama.exe")
    if not ollama_exe:
        candidate = (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "Programs"
            / "Ollama"
            / "ollama.exe"
        )
        if candidate.is_file():
            ollama_exe = str(candidate)
    try:
        local_models = list_local_models()
        ollama_running = True
    except LocalAIError:
        local_models = []
        ollama_running = False

    if ollama_running and local_models:
        ollama_status = "ok"
        ollama_msg = f"Đang chạy với {len(local_models)} model cục bộ: {', '.join(local_models)}"
        ollama_hint = None
    elif ollama_running:
        ollama_status = "warning"
        ollama_msg = "Ollama đang chạy nhưng chưa cài model cục bộ."
        ollama_hint = "ollama pull qwen3.5:4b"
    else:
        ollama_status = "warning"
        ollama_msg = "Ollama chưa chạy hoặc chưa thể kết nối qua 127.0.0.1:11434 (tùy chọn)."
        ollama_hint = "Mở Ollama và chạy: ollama pull qwen3.5:4b"

    openai_key_configured = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    openai_model = os.environ.get("OFFICEFLOW_OPENAI_MODEL", "gpt-6-luna")

    office_ready = bool(lo_path) and staging_ok
    ocr_ready = bool(ocrmypdf_path and tesseract_path and has_vie) and staging_ok

    return {
        "schema_version": "1.0",
        "app_version": __version__,
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "summary": {
            "office_ready": office_ready,
            "ocr_ready": ocr_ready,
            "desktop_ready": webview_installed,
            "local_ai_ready": ollama_running and bool(local_models),
        },
        "checks": {
            "libreoffice": {
                "status": "ok" if lo_path else "missing",
                "available": bool(lo_path),
                "path": lo_path,
                "version": lo_version,
                "message_vi": (
                    f"Sẵn sàng tại {lo_path}"
                    if lo_path
                    else "Chưa tìm thấy LibreOffice Desktop (soffice.exe)."
                ),
                "hint_vi": (
                    None
                    if lo_path
                    else "winget install -e --id TheDocumentFoundation.LibreOffice"
                ),
            },
            "ocrmypdf": {
                "status": "ok" if ocrmypdf_path else "missing",
                "available": bool(ocrmypdf_path),
                "path": ocrmypdf_path,
                "version": ocrmypdf_version,
                "message_vi": (
                    f"Sẵn sàng ({ocrmypdf_version or 'installed'})"
                    if ocrmypdf_path
                    else "Chưa tìm thấy OCRmyPDF trong môi trường Python."
                ),
                "hint_vi": None if ocrmypdf_path else "uv pip install -e .",
            },
            "tesseract": {
                "status": "ok" if tesseract_path else "missing",
                "available": bool(tesseract_path),
                "path": str(tesseract_path) if tesseract_path else None,
                "version": tesseract_version,
                "message_vi": (
                    f"Sẵn sàng ({tesseract_version or tesseract_path})"
                    if tesseract_path
                    else "Chưa tìm thấy Tesseract OCR (tesseract.exe)."
                ),
                "hint_vi": (
                    None if tesseract_path else "winget install -e --id tesseract-ocr.tesseract"
                ),
            },
            "tessdata": {
                "status": tess_status,
                "available": has_vie,
                "path": tess_info.get("resolved_dir"),
                "details": tess_info,
                "message_vi": tess_msg,
                "hint_vi": tess_hint,
            },
            "staging": {
                "status": "ok" if staging_ok else "missing",
                "available": staging_ok,
                "path": str(STAGING_ROOT),
                "details": {"is_symlink": staging_is_symlink},
                "message_vi": (
                    f"Vùng tạm cục bộ hợp lệ: {STAGING_ROOT}"
                    if staging_ok
                    else "Thư mục staging gốc là symlink không an toàn."
                ),
                "hint_vi": None,
            },
            "pywebview": {
                "status": "ok" if webview_installed else "warning",
                "available": webview_installed,
                "version": webview_version,
                "message_vi": (
                    f"Cửa sổ desktop sẵn sàng (pywebview {webview_version})"
                    if webview_installed
                    else "Chưa cài extra desktop (tùy chọn)."
                ),
                "hint_vi": None if webview_installed else 'uv pip install -e ".[desktop]"',
            },
            "ollama": {
                "status": ollama_status,
                "available": ollama_running and bool(local_models),
                "path": ollama_exe,
                "details": {
                    "service_running": ollama_running,
                    "models": local_models,
                },
                "message_vi": ollama_msg,
                "hint_vi": ollama_hint,
            },
            "openai": {
                "status": "ok" if openai_key_configured else "info",
                "available": openai_key_configured,
                "details": {
                    "api_key_configured": openai_key_configured,
                    "default_model": openai_model,
                },
                "message_vi": (
                    "OPENAI_API_KEY đã cấu hình (tùy chọn cloud)."
                    if openai_key_configured
                    else "OPENAI_API_KEY chưa đặt (tùy chọn cloud)."
                ),
                "hint_vi": None,
            },
        },
    }


def format_doctor_json(report: Mapping[str, Any]) -> str:
    """Format diagnostic report as pretty UTF-8 JSON."""
    return json.dumps(report, ensure_ascii=False, indent=2)


def format_doctor_text(report: Mapping[str, Any]) -> str:
    """Format diagnostic report in human-readable Vietnamese for Windows terminals."""
    py_info = report.get("python", {})
    summary = report.get("summary", {})
    checks = report.get("checks", {})
    lines = [
        f"OfficeFlow Doctor v{report.get('app_version', '')} · Python {py_info.get('version', '')}",
        "-" * 68,
    ]
    labels = [
        ("libreoffice", "Chuyển Office (LibreOffice)"),
        ("ocrmypdf", "Bộ điều phối OCR (OCRmyPDF)"),
        ("tesseract", "Máy nhận dạng chữ (Tesseract)"),
        ("tessdata", "Gói ngôn ngữ OCR (tessdata)"),
        ("staging", "Thư mục tạm (Staging)"),
        ("pywebview", "Cửa sổ Desktop (pywebview)"),
        ("ollama", "AI cục bộ (Ollama)"),
        ("openai", "AI đám mây (OpenAI API)"),
    ]
    status_badges = {
        "ok": "[OK]",
        "warning": "[CANH BAO]",
        "info": "[TUY CHON]",
        "missing": "[THIEU]",
    }
    for key, title in labels:
        item = checks.get(key, {})
        badge = status_badges.get(str(item.get("status", "")), "[INFO]")
        lines.append(f"{badge:10} {title}: {item.get('message_vi', '')}")
        hint = item.get("hint_vi")
        if hint:
            lines.append(f"           Gợi ý: {hint}")

    lines.append("-" * 68)
    office_str = "Sẵn sàng" if summary.get("office_ready") else "Chưa sẵn sàng"
    ocr_str = "Sẵn sàng" if summary.get("ocr_ready") else "Chưa sẵn sàng"
    ai_str = "Sẵn sàng" if summary.get("local_ai_ready") else "Tùy chọn"
    lines.append(f"Tổng kết: Office: {office_str} | OCR: {ocr_str} | AI cục bộ: {ai_str}")
    return "\n".join(lines)

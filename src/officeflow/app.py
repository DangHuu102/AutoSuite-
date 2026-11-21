"""Web application interface for AutoSuite: PDF-to-Word (preserving tables) and Office/Scan-to-PDF."""

from __future__ import annotations

import base64
import html
import io
import json
import os
from pathlib import Path
from typing import Any
import zipfile

import streamlit as st
import streamlit.components.v1 as components

from officeflow.ai_filter import (
    LocalAIError,
    classify_pdf_batch,
    list_local_models,
    suggest_filter,
    suggest_filter_openai,
)
from officeflow.batch import (
    cancel_batch,
    convert_batch,
    create_batch_job,
    create_retry_batch,
)
from officeflow.converter import LibreOfficeConverter, find_libreoffice
from officeflow.messages_vi import (
    APP_TITLE,
    BATCH_STATE_LABELS,
    LIBREOFFICE_MISSING,
    OUTPUT_STATUS_LABELS,
    SOURCE_STATUS_LABELS,
)
from officeflow.models import BatchJob, BatchState, OutputPdf, OutputStatus, SourceStatus
from officeflow.naming import (
    normalize_docx_name,
    normalize_pdf_name,
    resolve_unique_docx_names,
    resolve_unique_pdf_names,
)
from officeflow.ocr import OCRProcessor, find_ocrmypdf
from officeflow.reporting import (
    build_batch_report,
    format_report_csv,
    format_report_json,
)
from officeflow.staging import cleanup_orphaned_staging_once
from officeflow.validation import (
    IMAGE_EXTENSIONS,
    MAX_BATCH_BYTES,
    MAX_FILES_PER_BATCH,
    OFFICE_EXTENSIONS,
)

_CSS = """
<style>
:root { --ink:#17243b; --muted:#61718a; --line:#dfe7f1; --blue:#3159c9; --teal:#0c8b83; }
.stApp { background:linear-gradient(180deg,#f7f9fd 0%,#f3f6fb 100%); color:var(--ink); }
[data-testid="stAppViewContainer"] > .main .block-container { max-width:1180px; padding-top:1.2rem; padding-bottom:3rem; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stAppDeployButton"], .stAppDeployButton { display:none !important; }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:14px; padding:.65rem .8rem; }
[data-testid="stMetricLabel"] { color:var(--muted); }
[data-testid="stAlert"] { border-radius:12px; }
.stButton > button, .stDownloadButton > button { border-radius:10px; min-height:2.75rem; font-weight:650; color:#17243b !important; background:#fff !important; border:1px solid #cbd6e5 !important; }
.stButton > button:hover:not(:disabled), .stDownloadButton > button:hover:not(:disabled) { color:#183a75 !important; background:#edf3ff !important; border-color:#9bb3ef !important; }
.stButton > button:disabled, .stDownloadButton > button:disabled { color:#66758d !important; background:#e7edf6 !important; border-color:#d1dae7 !important; opacity:1 !important; }
.stButton > button[data-testid="stBaseButton-primary"], .stButton > button[kind="primary"] { color:#fff !important; background:#3159c9 !important; border-color:#3159c9 !important; }
.stButton > button[data-testid="stBaseButton-primary"]:hover:not(:disabled), .stButton > button[kind="primary"]:hover:not(:disabled) { color:#fff !important; background:#2448ad !important; border-color:#2448ad !important; }
.stButton > button[data-testid="stBaseButton-primary"]:disabled, .stButton > button[kind="primary"]:disabled { color:#66758d !important; background:#e7edf6 !important; border-color:#d1dae7 !important; opacity:1 !important; }
.stTextInput input, .stSelectbox div[data-baseweb="select"] { border-radius:10px; color:#17243b !important; background:#fff !important; }
.stSelectbox [role="combobox"] { color:#17243b !important; }
[data-testid="stFileUploaderDropzone"] { background:#fff !important; border:1px dashed #9aa9bd !important; }
[data-testid="stFileUploaderDropzoneInstructions"], [data-testid="stFileUploaderDropzoneInstructions"] * { color:#45536a !important; }
[data-testid="stFileUploaderDropzone"] button { color:#17243b !important; background:#fff !important; border-color:#cbd6e5 !important; }
[data-testid="stFileUploaderDropzone"] button:hover:not(:disabled) { color:#17243b !important; background:#edf3ff !important; border-color:#9bb3ef !important; }
[data-testid="stFileUploaderDropzone"] button * { color:#17243b !important; }
.brand-panel { border-radius:22px; padding:1.4rem 1.7rem; margin:.25rem 0 1.1rem; color:#fff;
 background:radial-gradient(circle at 88% 15%,rgba(123,210,223,.42),transparent 25%),linear-gradient(120deg,#163b76 0%,#295bc5 60%,#337cc6 100%);
 box-shadow:0 14px 35px rgba(30,69,133,.15); }
.brand-kicker { opacity:.8; font-size:.75rem; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }
.brand-panel h1 { color:#fff; margin:.25rem 0 .35rem; font-size:1.75rem; letter-spacing:-.03em; }
.brand-panel p { color:#e5efff; max-width:780px; margin:0; line-height:1.55; }
.step-strip { display:flex; gap:.6rem; margin:.3rem 0 1.4rem; }
.step-item { flex:1; display:flex; align-items:center; gap:.55rem; padding:.7rem .8rem; border:1px solid var(--line); border-radius:12px; background:#fff; color:var(--muted); font-size:.87rem; }
.step-item.active { border-color:#9bb3ef; background:#edf3ff; color:#2148a8; font-weight:700; }
.step-item.done { border-color:#a9ded7; background:#eefaf7; color:#08766e; }
.step-dot { display:grid; place-items:center; width:1.55rem; height:1.55rem; border-radius:50%; background:#edf1f7; color:#53637d; font-size:.76rem; font-weight:800; flex:0 0 auto; }
.step-item.active .step-dot { background:#3159c9; color:#fff; }
.step-item.done .step-dot { background:#0c8b83; color:#fff; }
.section-kicker { color:#3159c9; text-transform:uppercase; font-size:.72rem; letter-spacing:.1em; font-weight:800; margin-bottom:.15rem; }
@media(max-width:700px) { .step-strip { flex-direction:column; } .brand-panel { padding:1.15rem; } .brand-panel h1 { font-size:1.45rem; } }
</style>
"""


def _init_session() -> None:
    """Pure web session state: never reads or queries the host machine's user directories."""
    st.session_state.setdefault("officeflow_jobs", [])
    st.session_state.setdefault("officeflow_active_job", None)
    st.session_state.setdefault("officeflow_target_format", "docx")
    st.session_state.setdefault("officeflow_ocr_language", "vie")
    st.session_state.setdefault("officeflow_ai_models", [])
    st.session_state.setdefault("officeflow_ai_suggestions", {})


def _active_job() -> BatchJob | None:
    active_id = st.session_state.get("officeflow_active_job")
    return next(
        (job for job in st.session_state["officeflow_jobs"] if job.batch_id == active_id),
        None,
    )


def _add_job(job: BatchJob) -> None:
    st.session_state["officeflow_jobs"].append(job)
    st.session_state["officeflow_active_job"] = job.batch_id


def _source_by_id(job: BatchJob, source_id: str) -> Any | None:
    return next((source for source in job.sources if source.source_id == source_id), None)


def _output_by_id(job: BatchJob, output_id: str) -> OutputPdf | None:
    return next((output for output in job.outputs if output.output_id == output_id), None)


def _output_source_label(job: BatchJob, output: OutputPdf) -> str:
    ids = output.related_source_ids
    if len(ids) > 1:
        names = [
            s.original_name
            for sid in ids
            if (s := _source_by_id(job, sid)) is not None
        ]
        preview = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
        return f"Ảnh ghép ({len(ids)} tệp: {preview})" if preview else f"Ảnh ghép ({len(ids)} tệp)"
    source = _source_by_id(job, output.source_id)
    return source.original_name if source else "Tệp nguồn"


def _normalize_for_job(job: BatchJob, raw_name: str) -> str:
    if job.target_format == "docx":
        return normalize_docx_name(raw_name)
    return normalize_pdf_name(raw_name)


def _resolve_unique_in_batch(job: BatchJob, names: list[str]) -> list[str]:
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


def _apply_ai_name(job_id: str, output_id: str) -> None:
    suggestions = st.session_state.get("officeflow_ai_suggestions", {}).get(job_id, {})
    suggestion = suggestions.get(output_id)
    job = next((j for j in st.session_state.get("officeflow_jobs", []) if j.batch_id == job_id), None)
    if suggestion:
        name_key = f"officeflow-final-{job_id}-{output_id}"
        try:
            if job and job.target_format == "docx":
                st.session_state[name_key] = normalize_docx_name(suggestion.suggested_basename)
            else:
                st.session_state[name_key] = normalize_pdf_name(suggestion.suggested_basename)
        except ValueError:
            pass


def _render_browser_save_as_picker(
    job: BatchJob,
    selected_outputs: list[OutputPdf],
    names_by_id: dict[str, str],
) -> None:
    """Render a pure client-side browser 'Save As...' / folder picker widget (File System Access API).

    The browser opens the user's native OS Save As / Folder dialog so they can pick Drive D:, C:,
    or any folder on their own computer without the server ever querying their filesystem.
    """
    is_docx = job.target_format == "docx"
    ext = ".docx" if is_docx else ".pdf"
    mime = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if is_docx
        else "application/pdf"
    )
    desc = "Microsoft Word Document (.docx)" if is_docx else "PDF Document (.pdf)"

    files_payload: list[dict[str, str]] = []
    for output in selected_outputs:
        if output.staging_path is not None and output.staging_path.is_file():
            raw_name = names_by_id.get(output.output_id, output.final_name)
            try:
                safe_name = _normalize_for_job(job, raw_name)
            except ValueError:
                safe_name = output.final_name
            b64 = base64.b64encode(output.staging_path.read_bytes()).decode("ascii")
            files_payload.append({"name": safe_name, "b64": b64, "mime": mime})

    if not files_payload:
        return

    files_json = json.dumps(files_payload)
    btn_label = (
        f"💾 Chọn nơi lưu trên máy (Ổ D:, C:…) — {files_payload[0]['name']}"
        if len(files_payload) == 1
        else f"💾 Chọn thư mục trên máy (Ổ D:, C:…) để lưu {len(files_payload)} tệp"
    )

    widget_html = f"""
    <div style="font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 0;">
      <button id="autosuite-save-btn" style="
        width: 100%;
        min-height: 44px;
        padding: 10px 16px;
        border-radius: 10px;
        border: 1px solid #3159c9;
        background: #3159c9;
        color: #ffffff;
        font-size: 15px;
        font-weight: 650;
        cursor: pointer;
        transition: background 0.15s;
      ">{html.escape(btn_label)}</button>
      <div id="autosuite-save-status" style="margin-top: 6px; font-size: 13px; color: #08766e;"></div>
    </div>
    <script>
    (function() {{
      const files = {files_json};
      const ext = {json.dumps(ext)};
      const mime = {json.dumps(mime)};
      const desc = {json.dumps(desc)};
      const btn = document.getElementById("autosuite-save-btn");
      const status = document.getElementById("autosuite-save-status");

      function b64ToBytes(b64) {{
        const bin = atob(b64);
        const arr = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
        return arr;
      }}

      function fallbackDownload(fileObj) {{
        const blob = new Blob([b64ToBytes(fileObj.b64)], {{ type: fileObj.mime }});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fileObj.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }}

      btn.addEventListener("click", async () => {{
        status.style.color = "#2148a8";
        status.textContent = "Đang mở hộp thoại chọn ổ đĩa / thư mục trên máy của bạn…";
        const hostWin = (window.parent && window.parent.showSaveFilePicker) ? window.parent : window;
        try {{
          if (files.length === 1 && hostWin.showSaveFilePicker) {{
            const f = files[0];
            const handle = await hostWin.showSaveFilePicker({{
              suggestedName: f.name,
              types: [{{ description: desc, accept: {{ [mime]: [ext] }} }}]
            }});
            const writable = await handle.createWritable();
            await writable.write(b64ToBytes(f.b64));
            await writable.close();
            status.style.color = "#08766e";
            status.textContent = "✓ Đã lưu thành công tệp: " + handle.name;
            return;
          }}
          if (files.length > 1 && hostWin.showDirectoryPicker) {{
            const dirHandle = await hostWin.showDirectoryPicker({{ mode: "readwrite" }});
            for (const f of files) {{
              const fileHandle = await dirHandle.getFileHandle(f.name, {{ create: true }});
              const writable = await fileHandle.createWritable();
              await writable.write(b64ToBytes(f.b64));
              await writable.close();
            }}
            status.style.color = "#08766e";
            status.textContent = "✓ Đã lưu thành công " + files.length + " tệp vào thư mục: " + dirHandle.name;
            return;
          }}
          for (const f of files) fallbackDownload(f);
          status.style.color = "#08766e";
          status.textContent = "✓ Đã gửi tệp qua trình duyệt để bạn chọn nơi lưu.";
        }} catch (err) {{
          if (err && err.name === "AbortError") {{
            status.style.color = "#61718a";
            status.textContent = "Đã đóng hộp thoại chọn nơi lưu.";
            return;
          }}
          for (const f of files) fallbackDownload(f);
          status.style.color = "#08766e";
          status.textContent = "✓ Đã tải tệp qua trình duyệt.";
        }}
      }});
    }})();
    </script>
    """
    components.html(widget_html, height=76)


def _build_output_bundle_bytes(
    job: BatchJob,
    outputs: list[OutputPdf],
    names_by_id: dict[str, str] | None = None,
) -> tuple[bytes, str, str] | None:
    is_docx = job.target_format == "docx"
    default_ext = ".docx" if is_docx else ".pdf"
    single_mime = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if is_docx
        else "application/pdf"
    )
    available: list[tuple[Path, str]] = []
    for output in outputs:
        file_path = output.staging_path
        if file_path is not None and file_path.is_file():
            chosen_name = (
                names_by_id.get(output.output_id, output.final_name)
                if names_by_id
                else output.final_name
            )
            try:
                safe_name = _normalize_for_job(job, chosen_name)
            except ValueError:
                safe_name = output.final_name
            available.append((file_path, safe_name))
    if not available:
        return None
    if len(available) == 1:
        single_path, single_name = available[0]
        return single_path.read_bytes(), single_name, single_mime

    buf = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path, safe_name in available:
            candidate = safe_name
            stem = (
                candidate[: -len(default_ext)]
                if candidate.casefold().endswith(default_ext)
                else candidate
            )
            serial = 1
            while candidate.casefold() in used_names:
                candidate = f"{stem} ({serial}){default_ext}"
                serial += 1
            used_names.add(candidate.casefold())
            zf.write(file_path, arcname=candidate)
    zip_label = "AutoSuite-Word.zip" if is_docx else "AutoSuite-PDF.zip"
    return buf.getvalue(), zip_label, "application/zip"


def _format_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@st.cache_data(ttl=30, show_spinner=False)
def _cached_local_ai_status() -> tuple[bool, list[str]]:
    try:
        return True, list_local_models()
    except LocalAIError:
        return False, []


def _show_issue(issue: Any) -> None:
    if issue.severity == "warning":
        st.warning(issue.message_vi)
    else:
        st.error(issue.message_vi)


def _render_header(current_step: int) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        "<div class='brand-panel'><div class='brand-kicker'>AutoSuite · Web Document Converter</div>"
        "<h1>AutoSuite — Chuyển đổi PDF & Word (Giữ nguyên bảng biểu)</h1>"
        "<p>Tải tệp lên từ trình duyệt, chuyển PDF sang Word (.docx) giữ nguyên bảng biểu hoặc chuyển tài liệu/ảnh scan "
        "sang PDF có OCR, xem trước kết quả rồi bấm Lưu để chọn ổ đĩa bất kỳ trên máy bạn.</p></div>",
        unsafe_allow_html=True,
    )
    steps = ("1. Chọn công cụ & Tải tệp", "2. Xem trước & Lưu về máy")
    active_idx = 1 if current_step == 1 else 2
    blocks = []
    for index, label in enumerate(steps, start=1):
        state = "done" if index < active_idx else "active" if index == active_idx else ""
        shown = "✓" if index < active_idx else str(index)
        blocks.append(
            f"<div class='step-item {state}'><span class='step-dot'>{shown}</span>"
            f"<span>{html.escape(label)}</span></div>"
        )
    st.markdown("<div class='step-strip'>" + "".join(blocks) + "</div>", unsafe_allow_html=True)


def _new_batch_screen() -> None:
    st.markdown("<div class='section-kicker'>Bước 1 · Chọn công cụ & Tải tệp lên</div>", unsafe_allow_html=True)
    st.header("Chọn chế độ chuyển đổi")

    with st.container(border=True):
        target_format = st.radio(
            "Công cụ chuyển đổi",
            options=("docx", "pdf"),
            format_func=lambda mode: (
                "📝 Chuyển PDF sang Word (.docx) — Giữ nguyên bảng biểu & văn bản chỉnh sửa được"
                if mode == "docx"
                else "📄 Chuyển Word, Excel, PowerPoint, PDF scan & Ảnh sang PDF (có nhận diện chữ OCR)"
            ),
            key="officeflow_target_format",
        )

    allowed_types = (
        ["pdf"]
        if target_format == "docx"
        else ["docx", "xlsx", "pptx", "pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp"]
    )
    uploader_label = (
        "Tải tệp PDF cần chuyển sang Word (.docx)"
        if target_format == "docx"
        else "Tải tệp Word, Excel, PowerPoint, PDF scan hoặc Ảnh lên"
    )

    with st.container(border=True):
        uploads = st.file_uploader(
            uploader_label,
            type=allowed_types,
            accept_multiple_files=True,
            key=f"officeflow_new_uploads_{target_format}",
            max_upload_size=100,
        )
        file_count = len(uploads or [])
        total_bytes = sum(getattr(upload, "size", 0) for upload in (uploads or []))
        if uploads:
            st.caption(f"Tổng dung lượng: **{_format_size(total_bytes)}**")
            if file_count > MAX_FILES_PER_BATCH:
                st.error(f"Mỗi lô nhận tối đa {MAX_FILES_PER_BATCH} tệp.")
            elif total_bytes > MAX_BATCH_BYTES:
                st.error("Lô vượt quá 500 MB. Hãy chia nhỏ thành nhiều lô.")

    with st.expander("Tùy chọn nâng cao (Ngôn ngữ OCR / Ghép nhiều ảnh)", expanded=False):
        st.selectbox(
            "Ngôn ngữ nhận diện chữ (OCR cho PDF scan / ảnh)",
            options=("vie", "eng", "vie+eng"),
            format_func=lambda code: {
                "vie": "Tiếng Việt",
                "eng": "Tiếng Anh",
                "vie+eng": "Tiếng Việt + tiếng Anh",
            }[code],
            key="officeflow_ocr_language",
        )
        merge_images = False
        merged_pdf_name = "Anh-gop.pdf"
        if target_format == "pdf":
            merge_images = st.checkbox(
                "Ghép các ảnh scan đã chọn thành một PDF nhiều trang",
                key="officeflow_merge_images",
            )
            if merge_images:
                merged_pdf_name = st.text_input(
                    "Tên PDF sau khi ghép ảnh",
                    value=st.session_state.get("officeflow_merged_pdf_name", "Anh-gop.pdf"),
                    key="officeflow_merged_pdf_name",
                )

    invalid_size = total_bytes > MAX_BATCH_BYTES or file_count > MAX_FILES_PER_BATCH
    action_label = (
        "🚀 Chuyển sang Word (.docx) ngay"
        if target_format == "docx"
        else "🚀 Chuyển sang PDF ngay"
    )
    if st.button(
        action_label,
        type="primary",
        disabled=not uploads or invalid_size,
        use_container_width=True,
    ):
        try:
            job = create_batch_job(
                uploads,
                None,
                st.session_state["officeflow_ocr_language"],
                merge_images=bool(merge_images),
                merged_pdf_name=merged_pdf_name,
                target_format=target_format,
            )
            valid_sources = [s for s in job.sources if s.status is SourceStatus.VALID]
            if valid_sources:
                is_docx = job.target_format == "docx"
                valid_office = any(s.extension in OFFICE_EXTENSIONS for s in valid_sources)
                valid_ocr = any(s.extension == ".pdf" or s.extension in IMAGE_EXTENSIONS for s in valid_sources)
                lo_exe = find_libreoffice() if not is_docx and valid_office else None
                ocr_exe = find_ocrmypdf() if valid_ocr or is_docx else None
                office_converter = LibreOfficeConverter(executable=lo_exe) if lo_exe else None
                ocr_processor = OCRProcessor(executable=ocr_exe) if ocr_exe else None
                progress_bar = st.progress(0.0, text="Đang chuyển đổi tài liệu…")

                def update_progress(completed: int, total: int, source: Any) -> None:
                    progress_bar.progress(
                        completed / total if total else 1.0,
                        text=f"Đang xử lý {completed}/{total}: {source.original_name}",
                    )

                convert_batch(job, office_converter, ocr_processor, update_progress)
            else:
                job.state = BatchState.REVIEW
            _add_job(job)
            st.rerun()
        except (OSError, RuntimeError, ValueError) as exc:
            st.error(str(exc))


def _load_ai_models() -> None:
    try:
        st.session_state["officeflow_ai_models"] = list_local_models()
        if not st.session_state["officeflow_ai_models"]:
            st.warning("Chưa có model AI cục bộ trong Ollama.")
    except LocalAIError as exc:
        st.error(str(exc))


def _ai_filter_panel(job: BatchJob) -> None:
    if job.target_format == "docx":
        return
    with st.expander("AI lọc tài liệu và gợi ý tên PDF (Tùy chọn)", expanded=False):
        st.caption(
            "Mỗi lượt chỉ đọc tối đa 8 trang đầu và 12.000 ký tự trích từ PDF. "
            "AI chỉ đưa gợi ý; bạn vẫn là người quyết định."
        )
        provider = st.radio(
            "Chọn AI",
            options=["ollama", "openai"],
            format_func=lambda value: "Ollama chạy cục bộ" if value == "ollama" else "OpenAI API",
            horizontal=True,
            key=f"officeflow-ai-provider-{job.batch_id}",
        )
        cloud_consent = False
        api_key_available = bool(os.environ.get("OPENAI_API_KEY", "").strip())
        if provider == "ollama":
            if not st.session_state.get("officeflow_ai_models"):
                _, cached_models = _cached_local_ai_status()
                if cached_models:
                    st.session_state["officeflow_ai_models"] = list(cached_models)
            if st.button("Kiểm tra model Ollama", key=f"officeflow-ai-refresh-{job.batch_id}"):
                _load_ai_models()
            models = st.session_state.get("officeflow_ai_models", [])
            if models:
                model = st.selectbox(
                    "Model AI", options=models, key=f"officeflow-ai-model-{job.batch_id}"
                )
            else:
                model = ""
                st.info("Mở Ollama và bấm kiểm tra danh sách model.")
        else:
            cloud_consent = st.checkbox(
                "Tôi đồng ý gửi tối đa 8 trang đầu (không quá 12.000 ký tự) tới OpenAI API.",
                key=f"officeflow-ai-cloud-consent-{job.batch_id}",
            )
            model = st.text_input(
                "Mã model OpenAI",
                value=os.environ.get("OFFICEFLOW_OPENAI_MODEL", "gpt-6-luna"),
                key=f"officeflow-openai-model-{job.batch_id}",
            ).strip()

        filter_request = st.text_input(
            "Tiêu chí lọc tài liệu",
            value="Giữ giấy tờ hành chính và hồ sơ học tập; xem lại tài liệu chưa rõ.",
            key=f"officeflow-ai-request-{job.batch_id}",
        )
        suggestions_key = "officeflow_ai_suggestions"
        request_key = f"officeflow-ai-request-used-{job.batch_id}"
        model_key = f"officeflow-ai-model-used-{job.batch_id}"
        error_key = f"officeflow-ai-errors-{job.batch_id}"
        reviewed_key = f"officeflow-ai-reviewed-{job.batch_id}"
        existing = st.session_state[suggestions_key].get(job.batch_id, {})
        used_request = st.session_state.get(request_key, "")
        used_model = st.session_state.get(model_key, "")
        selected_model_id = f"{provider}:{model}"
        request_is_current = (
            bool(used_request)
            and used_request == filter_request.strip()
            and used_model == selected_model_id
        )

        ai_disabled = (
            not job.outputs
            or not filter_request.strip()
            or not model
            or (provider == "openai" and (not cloud_consent or not api_key_available))
        )
        if st.button(
            f"Phân loại toàn bộ {len(job.outputs)} PDF bằng AI",
            type="secondary",
            key=f"officeflow-ai-run-all-{job.batch_id}",
            disabled=ai_disabled,
            use_container_width=True,
        ):
            suggestions = {}
            errors = {}
            progress_bar = st.progress(0.0, text="Đang phân loại…")
            items = []
            for output in job.outputs:
                source = _source_by_id(job, output.source_id)
                label = source.original_name if source else output.final_name
                path = output.staging_path if output.staging_path is not None else Path()
                items.append((output.output_id, path, label))

            def _on_ai_progress(index: int, total: int, label: str) -> None:
                progress_bar.progress(
                    index / total if total else 1.0,
                    text=f"Đang phân loại {index}/{total}: {label}",
                )

            try:
                batch_results = classify_pdf_batch(
                    items,
                    provider=provider,
                    model=model,
                    filter_request=filter_request,
                    allow_cloud=cloud_consent,
                    progress_callback=_on_ai_progress,
                )
                for res in batch_results:
                    if res.suggestion is not None:
                        suggestions[res.item_id] = res.suggestion
                    elif res.error:
                        errors[res.item_id] = res.error
            except (LocalAIError, OSError, ValueError) as exc:
                if job.outputs:
                    errors[job.outputs[0].output_id] = str(exc)

            st.session_state[suggestions_key][job.batch_id] = suggestions
            st.session_state[request_key] = filter_request.strip()
            st.session_state[model_key] = selected_model_id
            st.session_state[error_key] = errors
            st.session_state[reviewed_key] = False
            st.rerun()

        if existing:
            for output in job.outputs:
                suggestion = existing.get(output.output_id)
                if not suggestion:
                    continue
                source = _source_by_id(job, output.source_id)
                decision_label = {"keep": "Gợi ý giữ", "skip": "Gợi ý bỏ qua", "review": "Cần xem lại"}.get(
                    suggestion.decision, "Gợi ý AI"
                )
                st.write(
                    f"**{source.original_name if source else output.final_name}** · "
                    f"{decision_label} · {suggestion.category}"
                )
                st.caption(f"{suggestion.reason} · Tên đề xuất: {suggestion.suggested_basename}")
            reviewed = st.checkbox(
                "Tôi đã xem các gợi ý của AI.",
                key=reviewed_key,
                disabled=not request_is_current,
            )
            apply_col, names_col = st.columns(2)
            with apply_col:
                if st.button(
                    "Áp dụng gợi ý chọn tệp",
                    key=f"officeflow-ai-apply-{job.batch_id}",
                    disabled=not reviewed or not request_is_current,
                    use_container_width=True,
                ):
                    for output in job.outputs:
                        suggestion = existing.get(output.output_id)
                        if suggestion and suggestion.decision in {"keep", "skip"}:
                            st.session_state[f"officeflow-save-{job.batch_id}-{output.output_id}"] = (
                                suggestion.decision == "keep"
                            )
                    st.rerun()
            with names_col:
                if st.button(
                    "Dùng tất cả tên gợi ý",
                    key=f"officeflow-ai-apply-names-{job.batch_id}",
                    disabled=not reviewed or not request_is_current,
                    use_container_width=True,
                ):
                    for output in job.outputs:
                        _apply_ai_name(job.batch_id, output.output_id)
                    st.rerun()


def _render_word_preview(output: OutputPdf) -> None:
    blocks = output.preview_blocks or []
    with st.container(border=True):
        st.markdown(
            f"**Xem trước nội dung Word (`{output.final_name}`)** · "
            f"{output.page_count or 1} trang · **{output.table_count or 0} bảng biểu giữ nguyên**"
        )
        if not blocks:
            st.caption("Đã tạo tệp Word (.docx). Bấm nút Lưu bên dưới để chọn ổ đĩa lưu tệp.")
            return
        current_page = None
        for block in blocks:
            page_no = block.get("page", 1)
            if page_no != current_page:
                current_page = page_no
                st.caption(f"— Trang {current_page} —")
            if block.get("type") == "table":
                rows = block.get("rows", [])
                if rows:
                    st.table(rows)
            else:
                text = str(block.get("text", ""))
                if block.get("heading"):
                    st.markdown(f"**{html.escape(text)}**")
                else:
                    st.write(text)


def _review_screen(job: BatchJob) -> None:
    is_docx = job.target_format == "docx"
    out_label = "Word (.docx)" if is_docx else "PDF"
    st.markdown("<div class='section-kicker'>Bước 2 · Xem trước & Lưu về máy</div>", unsafe_allow_html=True)
    st.header(f"Kết quả {out_label} — Xem trước và chọn nơi lưu")

    for source in job.sources:
        for issue in source.issues:
            _show_issue(issue)

    if not job.outputs:
        st.warning(f"Không tạo được tệp {out_label} nào từ tệp đã chọn.")
        if st.button("Quay lại chuyển đổi tệp khác", type="primary"):
            cancel_batch(job)
            st.session_state["officeflow_active_job"] = None
            st.rerun()
        return

    _ai_filter_panel(job)

    selected_ids: set[str] = set()
    edited_names: dict[str, str] = {}
    for output in job.outputs:
        source_name = _output_source_label(job, output)
        select_key = f"officeflow-save-{job.batch_id}-{output.output_id}"
        name_key = f"officeflow-final-{job.batch_id}-{output.output_id}"
        st.session_state.setdefault(select_key, True)
        st.session_state.setdefault(name_key, output.final_name)
        with st.container(border=True):
            file_col, name_col, save_col = st.columns([2.3, 3.4, 1.0])
            with file_col:
                st.write(f"**{source_name}**")
                page_info = f"{output.page_count} trang" if output.page_count is not None else "1 trang"
                if is_docx:
                    detail_info = f"Giữ nguyên {output.table_count or 0} bảng biểu"
                elif output.searchable_text is None:
                    detail_info = "Tài liệu Office"
                elif output.searchable_text:
                    detail_info = "Có lớp chữ OCR"
                else:
                    detail_info = "Chưa phát hiện lớp chữ"
                st.caption(f"{page_info} · {detail_info}")
            with name_col:
                st.text_input(
                    f"Tên tệp {out_label}",
                    key=name_key,
                    label_visibility="collapsed",
                )
            with save_col:
                st.checkbox("Chọn", key=select_key)
            edited_names[output.output_id] = st.session_state[name_key]
            if st.session_state[select_key]:
                selected_ids.add(output.output_id)
            for issue in output.issues:
                _show_issue(issue)

    resolved_names: dict[str, str] = {}
    name_error: str | None = None
    if selected_ids:
        selected_outputs = [output for output in job.outputs if output.output_id in selected_ids]
        try:
            requested = [edited_names[output.output_id] for output in selected_outputs]
            normalized = [_normalize_for_job(job, name) for name in requested]
            unique_names = _resolve_unique_in_batch(job, normalized)
            for output, resolved in zip(selected_outputs, unique_names, strict=True):
                resolved_names[output.output_id] = resolved
        except ValueError as exc:
            name_error = str(exc)
            st.error(name_error)

    st.markdown("### Xem trước kết quả")
    output_ids = [output.output_id for output in job.outputs]
    selected_preview_id = (
        st.selectbox(
            f"Chọn tệp {out_label} để xem trước",
            options=output_ids,
            format_func=lambda output_id: _preview_label(job, output_id, edited_names),
            key=f"officeflow-preview-select-{job.batch_id}",
        )
        if len(output_ids) > 1
        else output_ids[0]
    )
    preview_output = _output_by_id(job, selected_preview_id)
    if preview_output and preview_output.staging_path and preview_output.staging_path.is_file():
        if is_docx:
            _render_word_preview(preview_output)
        else:
            try:
                st.pdf(
                    str(preview_output.staging_path),
                    height=580,
                    key=f"officeflow-preview-{job.batch_id}-{preview_output.output_id}",
                )
            except Exception:
                st.error("Không hiển thị được bản xem trước PDF.")

    st.divider()
    st.markdown("### Lưu tệp về máy của bạn")
    st.caption(
        "Bấm nút **Chọn nơi lưu trên máy** bên dưới để trình duyệt mở cửa sổ **Save As (Lưu dưới dạng)** — "
        "bạn có thể chọn **Ổ D:, Ổ C:, USB hoặc bất kỳ thư mục nào** trên máy tính của mình."
    )

    if selected_ids and not name_error:
        selected_outputs_for_save = [o for o in job.outputs if o.output_id in selected_ids]
        _render_browser_save_as_picker(job, selected_outputs_for_save, resolved_names or edited_names)

        dl_col, new_col = st.columns([1.8, 1.2])
        with dl_col:
            bundle = _build_output_bundle_bytes(job, selected_outputs_for_save, resolved_names or edited_names)
            if bundle is not None:
                b_data, b_name, b_mime = bundle
                st.download_button(
                    f"📥 Tải nhanh {b_name} qua trình duyệt",
                    data=b_data,
                    file_name=b_name,
                    mime=b_mime,
                    key=f"officeflow-review-dl-{job.batch_id}",
                    use_container_width=True,
                )
        with new_col:
            if st.button("🔄 Chuyển đổi tệp khác", use_container_width=True):
                cancel_batch(job)
                st.session_state["officeflow_active_job"] = None
                st.rerun()
    else:
        if st.button("🔄 Quay lại chuyển đổi tệp khác", use_container_width=True):
            cancel_batch(job)
            st.session_state["officeflow_active_job"] = None
            st.rerun()


def _preview_label(job: BatchJob, output_id: str, names: dict[str, str]) -> str:
    output = _output_by_id(job, output_id)
    if output is None:
        return "Tệp"
    source_name = _output_source_label(job, output)
    return f"{source_name} → {names.get(output_id, output.final_name)}"


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📄", layout="wide")
    _init_session()
    cleanup_orphaned_staging_once()
    job = _active_job()
    step = 1 if job is None else 2
    _render_header(step)
    if job is None:
        _new_batch_screen()
    elif job.state is BatchState.PREFLIGHT:
        # In case a job is in preflight state, advance directly to review
        _review_screen(job)
    else:
        _review_screen(job)


if __name__ == "__main__":
    main()

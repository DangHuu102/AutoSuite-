"""Streamlit user interface for local batch conversion and OCR."""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

import streamlit as st

from officeflow.ai_filter import LocalAIError, list_local_models, suggest_filter
from officeflow.batch import cancel_batch, commit_batch, convert_batch, create_batch_job, create_retry_batch
from officeflow.converter import LibreOfficeConverter, find_libreoffice
from officeflow.messages_vi import (
    APP_TITLE,
    BATCH_STATE_LABELS,
    LIBREOFFICE_MISSING,
    OUTPUT_STATUS_LABELS,
    SOURCE_STATUS_LABELS,
)
from officeflow.models import BatchJob, BatchState, OutputPdf, OutputStatus, SourceStatus
from officeflow.naming import normalize_pdf_name, resolve_unique_pdf_names
from officeflow.ocr import OCRProcessor, find_ocrmypdf
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
[data-testid="stAppViewContainer"] > .main .block-container { max-width:1220px; padding-top:1.4rem; padding-bottom:3rem; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:14px; padding:.65rem .8rem; }
[data-testid="stMetricLabel"] { color:var(--muted); }
[data-testid="stAlert"] { border-radius:12px; }
.stButton > button { border-radius:10px; min-height:2.75rem; font-weight:650; color:#17243b !important; background:#fff !important; border:1px solid #cbd6e5 !important; }
.stButton > button:hover:not(:disabled) { color:#183a75 !important; background:#edf3ff !important; border-color:#9bb3ef !important; }
.stButton > button:disabled { color:#66758d !important; background:#e7edf6 !important; border-color:#d1dae7 !important; opacity:1 !important; }
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
.brand-panel { border-radius:22px; padding:1.45rem 1.7rem; margin:.35rem 0 1.1rem; color:#fff;
 background:radial-gradient(circle at 88% 15%,rgba(123,210,223,.42),transparent 25%),linear-gradient(120deg,#163b76 0%,#295bc5 60%,#337cc6 100%);
 box-shadow:0 14px 35px rgba(30,69,133,.15); }
.brand-kicker { opacity:.8; font-size:.75rem; font-weight:750; letter-spacing:.12em; text-transform:uppercase; }
.brand-panel h1 { color:#fff; margin:.25rem 0 .35rem; font-size:1.8rem; letter-spacing:-.03em; }
.brand-panel p { color:#e5efff; max-width:760px; margin:0; line-height:1.55; }
.step-strip { display:flex; gap:.6rem; margin:.3rem 0 1.5rem; }
.step-item { flex:1; display:flex; align-items:center; gap:.55rem; padding:.7rem .8rem; border:1px solid var(--line); border-radius:12px; background:#fff; color:var(--muted); font-size:.87rem; }
.step-item.active { border-color:#9bb3ef; background:#edf3ff; color:#2148a8; font-weight:700; }
.step-item.done { border-color:#a9ded7; background:#eefaf7; color:#08766e; }
.step-dot { display:grid; place-items:center; width:1.55rem; height:1.55rem; border-radius:50%; background:#edf1f7; color:#53637d; font-size:.76rem; font-weight:800; flex:0 0 auto; }
.step-item.active .step-dot { background:#3159c9; color:#fff; }
.step-item.done .step-dot { background:#0c8b83; color:#fff; }
.section-kicker { color:#3159c9; text-transform:uppercase; font-size:.72rem; letter-spacing:.1em; font-weight:800; margin-bottom:.15rem; }
.subtle { color:#61718a; }
@media(max-width:700px) { .step-strip { flex-direction:column; } .brand-panel { padding:1.15rem; } .brand-panel h1 { font-size:1.45rem; } }
</style>
"""


def _default_destination() -> str:
    home = Path.home()
    for candidate in (home / "Desktop", home / "Documents"):
        if candidate.is_dir():
            return str(candidate)
    return str(home)


def _init_session() -> None:
    st.session_state.setdefault("officeflow_jobs", [])
    st.session_state.setdefault("officeflow_active_job", None)
    st.session_state.setdefault("officeflow_destination", _default_destination())
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


def _apply_ai_name(job_id: str, output_id: str) -> None:
    suggestions = st.session_state.get("officeflow_ai_suggestions", {}).get(job_id, {})
    suggestion = suggestions.get(output_id)
    if suggestion:
        name_key = f"officeflow-final-{job_id}-{output_id}"
        try:
            st.session_state[name_key] = normalize_pdf_name(suggestion.suggested_basename)
        except ValueError:
            pass


def _folder_picker() -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Chọn thư mục lưu PDF")
        root.destroy()
        if selected:
            st.session_state["officeflow_destination"] = selected
    except Exception:
        st.warning("Không mở được cửa sổ chọn thư mục. Bạn có thể dán đường dẫn vào ô bên cạnh.")


def _destination_from_text(value: str) -> Path:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("Hãy chọn thư mục đích để lưu PDF.")
    expanded = os.path.expandvars(raw_value)
    path = Path(expanded).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Thư mục đích chưa tồn tại hoặc không hợp lệ.")
    return path


def _format_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _show_issue(issue: Any) -> None:
    if issue.severity == "warning":
        st.warning(issue.message_vi)
    else:
        st.error(issue.message_vi)


def _render_header(current_step: int) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        "<div class='brand-panel'><div class='brand-kicker'>OfficeFlow · xử lý tại máy</div>"
        "<h1>Chuyển tài liệu sang PDF</h1>"
        "<p>Word, Excel, PowerPoint và tài liệu scan trong một luồng rõ ràng: kiểm tra, xem trước, "
        "rồi mới lưu. OCR và gợi ý AI cục bộ luôn nằm trong quyền kiểm soát của bạn.</p></div>",
        unsafe_allow_html=True,
    )
    steps = ("Chọn tệp", "Tạo PDF", "Duyệt & lưu")
    blocks = []
    for index, label in enumerate(steps, start=1):
        state = "done" if index < current_step else "active" if index == current_step else ""
        shown = "✓" if index < current_step else str(index)
        blocks.append(
            f"<div class='step-item {state}'><span class='step-dot'>{shown}</span>"
            f"<span>{html.escape(label)}</span></div>"
        )
    st.markdown("<div class='step-strip'>" + "".join(blocks) + "</div>", unsafe_allow_html=True)


def _destination_controls(disabled: bool = False) -> None:
    with st.container(border=True):
        st.markdown("### Thư mục lưu PDF")
        folder_col, path_col = st.columns([1.2, 4])
        with folder_col:
            st.button(
                "Chọn thư mục…",
                key="officeflow_pick_destination",
                on_click=_folder_picker,
                disabled=disabled,
                use_container_width=True,
            )
        with path_col:
            st.text_input(
                "Đường dẫn thư mục",
                key="officeflow_destination",
                disabled=disabled,
                help="Bạn cũng có thể dán đường dẫn Windows vào ô này.",
                label_visibility="collapsed",
            )


def _new_batch_screen() -> None:
    st.markdown("<div class='section-kicker'>Bước 1 · Chuẩn bị</div>", unsafe_allow_html=True)
    st.header("Chọn tài liệu cần xử lý")
    st.caption(
        "Mỗi tệp tạo một PDF riêng. Nhận Word, Excel, PowerPoint, PDF scan và ảnh; "
        "không tự quét thư mục con."
    )
    with st.expander("Vì sao cần LibreOffice cho tệp Office?", expanded=False):
        st.write(
            "Bản prototype dùng LibreOffice làm bộ máy đọc bố cục Word/Excel/PowerPoint và xuất PDF "
            "ngay trên máy. Python chỉ điều phối giao diện và lô tệp; Microsoft Office đã cài không "
            "được app tự điều khiển. Nếu chỉ chọn PDF hoặc ảnh scan để OCR thì LibreOffice không cần."
        )
    with st.container(border=True):
        uploads = st.file_uploader(
            "Chọn tệp từ máy tính",
            type=["docx", "xlsx", "pptx", "pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp"],
            accept_multiple_files=True,
            key="officeflow_new_uploads",
            max_upload_size=100,
            help="Tối đa 20 tệp, 100 MB mỗi tệp và tổng cộng 500 MB mỗi lô.",
        )
        file_count = len(uploads or [])
        total_bytes = sum(getattr(upload, "size", 0) for upload in (uploads or []))
        cap_col, single_col, total_col = st.columns(3)
        cap_col.metric("Số tệp tối đa", "20 tệp")
        single_col.metric("Mỗi tệp", "100 MB")
        total_col.metric("Tổng mỗi lô", "500 MB")
        if uploads:
            st.caption(f"Đã chọn **{file_count}** tệp · tổng dung lượng **{_format_size(total_bytes)}**.")
            if file_count > MAX_FILES_PER_BATCH:
                st.error(f"Mỗi lô nhận tối đa {MAX_FILES_PER_BATCH} tệp.")
            elif total_bytes > MAX_BATCH_BYTES:
                st.error("Lô vượt quá 500 MB. Hãy chia nhỏ thành nhiều lô.")
            else:
                with st.expander("Xem danh sách tệp đã chọn"):
                    for upload in uploads:
                        st.write(f"{upload.name} · {_format_size(upload.size)}")

    _destination_controls()
    with st.container(border=True):
        st.markdown("### Thiết lập OCR")
        st.caption("Chọn ngôn ngữ chữ in trong PDF/ảnh scan. Gói ngôn ngữ tương ứng cần có trên máy.")
        st.selectbox(
            "Ngôn ngữ OCR",
            options=("vie", "eng", "vie+eng"),
            format_func=lambda code: {
                "vie": "Tiếng Việt",
                "eng": "Tiếng Anh",
                "vie+eng": "Tiếng Việt + tiếng Anh",
            }[code],
            key="officeflow_ocr_language",
            label_visibility="collapsed",
        )

    invalid_size = total_bytes > MAX_BATCH_BYTES or file_count > MAX_FILES_PER_BATCH
    if st.button(
        "Kiểm tra tệp và tên PDF",
        type="primary",
        disabled=not uploads or invalid_size,
        use_container_width=True,
    ):
        try:
            destination = _destination_from_text(st.session_state["officeflow_destination"])
            job = create_batch_job(uploads, destination, st.session_state["officeflow_ocr_language"])
            _add_job(job)
            st.rerun()
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    _show_history()


def _job_capabilities(job: BatchJob) -> tuple[bool, bool, bool, bool]:
    valid = [source for source in job.sources if source.status is SourceStatus.VALID]
    needs_office = any(source.extension in OFFICE_EXTENSIONS for source in valid)
    needs_ocr = any(source.extension == ".pdf" or source.extension in IMAGE_EXTENSIONS for source in valid)
    return needs_office, needs_ocr, bool(find_libreoffice()), bool(find_ocrmypdf())


def _preflight_screen(job: BatchJob) -> None:
    st.markdown("<div class='section-kicker'>Bước 2 · Kiểm tra trước</div>", unsafe_allow_html=True)
    st.header("Kiểm tra tệp và tên đầu ra")
    st.caption(f"Thư mục lưu: `{job.destination}` · OCR: {job.ocr_language}")
    valid_sources = [source for source in job.sources if source.status is SourceStatus.VALID]
    count_cols = st.columns(3)
    count_cols[0].metric("Sẵn sàng", sum(s.status is SourceStatus.VALID for s in job.sources))
    count_cols[1].metric("Không hỗ trợ", sum(s.status is SourceStatus.SKIPPED for s in job.sources))
    count_cols[2].metric("Cần xử lý", sum(s.status is SourceStatus.FAILED for s in job.sources))
    st.info("Chưa có PDF nào được lưu vào thư mục đích. Bạn sẽ xem lại trước khi xác nhận.")

    for source in job.sources:
        with st.container(border=True):
            left, middle, right = st.columns([2.2, 1.15, 3])
            with left:
                st.write(source.original_name)
                st.caption(f"{source.extension or 'không có phần mở rộng'} · {_format_size(source.byte_size)}")
            with middle:
                st.write(SOURCE_STATUS_LABELS[source.status])
            with right:
                if source.status is SourceStatus.VALID:
                    name_key = f"officeflow-proposed-{job.batch_id}-{source.source_id}"
                    st.session_state.setdefault(name_key, source.proposed_output_name)
                    st.text_input("Tên PDF dự kiến", key=name_key, label_visibility="collapsed")
                else:
                    st.caption("Không có tên đầu ra")
            for issue in source.issues:
                _show_issue(issue)

    needs_office, needs_ocr, office_available, ocr_available = _job_capabilities(job)
    valid_office = any(s.status is SourceStatus.VALID and s.extension in OFFICE_EXTENSIONS for s in job.sources)
    valid_ocr = any(
        s.status is SourceStatus.VALID and (s.extension == ".pdf" or s.extension in IMAGE_EXTENSIONS)
        for s in job.sources
    )
    missing: list[str] = []
    if needs_office and not office_available:
        missing.append(LIBREOFFICE_MISSING)
    if needs_ocr and not ocr_available:
        missing.append("Không tìm thấy OCRmyPDF. Cài OCRmyPDF, Tesseract và gói ngôn ngữ OCR.")
    if missing:
        st.warning("Một số loại tệp chưa thể xử lý trên máy này:\n\n" + "\n\n".join(missing))
    if needs_ocr and ocr_available:
        st.caption("OCR chạy cục bộ. Thiếu traineddata sẽ được báo riêng cho từng tệp.")

    st.divider()
    action_col, cancel_col = st.columns([2, 1])
    with action_col:
        if st.button(
            "Tạo PDF để xem trước",
            type="primary",
            disabled=not valid_sources or not ((valid_office and office_available) or (valid_ocr and ocr_available)),
            use_container_width=True,
        ):
            try:
                edited_names = [
                    st.session_state.get(
                        f"officeflow-proposed-{job.batch_id}-{source.source_id}", source.proposed_output_name
                    )
                    for source in valid_sources
                ]
                clean_names = [normalize_pdf_name(value) for value in edited_names]
                final_names = resolve_unique_pdf_names(clean_names, job.destination)
                for source, name in zip(valid_sources, final_names, strict=True):
                    source.proposed_output_name = name

                office_converter = (
                    LibreOfficeConverter(executable=find_libreoffice()) if valid_office and office_available else None
                )
                ocr_processor = OCRProcessor(executable=find_ocrmypdf()) if valid_ocr and ocr_available else None
                progress_bar = st.progress(0.0, text="Đang chuẩn bị…")
                progress_text = st.empty()

                def update_progress(completed: int, total: int, source: Any) -> None:
                    progress_bar.progress(
                        completed / total if total else 1.0,
                        text=f"Đang xử lý {completed}/{total}: {source.original_name}",
                    )
                    progress_text.caption(SOURCE_STATUS_LABELS[source.status])

                convert_batch(job, office_converter, ocr_processor, update_progress)
                st.rerun()
            except (OSError, RuntimeError, ValueError) as exc:
                st.error(str(exc))
    with cancel_col:
        if st.button("Hủy lô", use_container_width=True):
            cancel_batch(job)
            st.rerun()


def _load_ai_models() -> None:
    try:
        st.session_state["officeflow_ai_models"] = list_local_models()
        if not st.session_state["officeflow_ai_models"]:
            st.warning("Chưa có model AI cục bộ trong Ollama. Ứng dụng không tự tải model.")
    except LocalAIError as exc:
        st.error(str(exc))


def _ai_filter_panel(job: BatchJob) -> None:
    with st.expander("Gợi ý lọc và đặt tên bằng AI cục bộ", expanded=False):
        st.caption(
            "AI chỉ đọc tối đa 8 trang đầu và 12.000 ký tự trích từ PDF tạm qua Ollama tại máy này. "
            "Mỗi lượt xử lý một tệp; chờ tối đa 45 giây theo mặc định (có thể tùy chỉnh 5–180 giây). "
            "Không gọi dịch vụ cloud."
        )
        if st.button("Kiểm tra model Ollama cục bộ", key=f"officeflow-ai-refresh-{job.batch_id}"):
            _load_ai_models()
        models = st.session_state.get("officeflow_ai_models", [])
        if not models:
            st.info("Mở Ollama, tải một model hỗ trợ tiếng Việt, rồi kiểm tra lại danh sách model.")
            return

        model = st.selectbox("Model AI đang cài", options=models, key=f"officeflow-ai-model-{job.batch_id}")
        filter_request = st.text_input(
            "Bạn muốn lọc tài liệu như thế nào?",
            value="Giữ giấy tờ hành chính và hồ sơ học tập; xem lại tài liệu chưa rõ.",
            key=f"officeflow-ai-request-{job.batch_id}",
            help="Ví dụ: Giữ hóa đơn năm 2026, xem lại hợp đồng và bỏ qua tài liệu cá nhân.",
        )
        suggestions_key = "officeflow_ai_suggestions"
        request_key = f"officeflow-ai-request-used-{job.batch_id}"
        model_key = f"officeflow-ai-model-used-{job.batch_id}"
        error_key = f"officeflow-ai-errors-{job.batch_id}"
        reviewed_key = f"officeflow-ai-reviewed-{job.batch_id}"
        existing = st.session_state[suggestions_key].get(job.batch_id, {})
        used_request = st.session_state.get(request_key, "")
        used_model = st.session_state.get(model_key, "")
        request_is_current = (
            bool(used_request)
            and used_request == filter_request.strip()
            and used_model == model
        )
        if existing and not request_is_current:
            st.warning("Tiêu chí hoặc model đã thay đổi. Chạy lại AI cho từng PDF cần dùng trước khi áp dụng các gợi ý cũ.")

        ai_file_id = st.selectbox(
            "Chọn một PDF để phân loại",
            options=[output.output_id for output in job.outputs],
            format_func=lambda output_id: _preview_label(
                job,
                output_id,
                {
                    output.output_id: st.session_state.get(
                        f"officeflow-final-{job.batch_id}-{output.output_id}", output.final_name
                    )
                    for output in job.outputs
                },
            ),
            key=f"officeflow-ai-file-{job.batch_id}",
        )
        if st.button(
            "Phân loại PDF đã chọn",
            type="secondary",
            key=f"officeflow-ai-run-{job.batch_id}",
            disabled=not job.outputs or not filter_request.strip(),
        ):
            suggestions = dict(existing) if request_is_current else {}
            errors = dict(st.session_state.get(error_key, {})) if request_is_current else {}
            output = _output_by_id(job, ai_file_id)
            try:
                if output is None or output.staging_path is None or not output.staging_path.is_file():
                    raise LocalAIError("Không tìm thấy PDF tạm để đọc.")
                source = _source_by_id(job, output.source_id)
                label = source.original_name if source else output.final_name
                with st.spinner(f"Đang phân tích {label} trên model cục bộ…"):
                    suggestions[output.output_id] = suggest_filter(
                        output.staging_path, model, filter_request, output.final_name
                    )
                errors.pop(output.output_id, None)
            except (LocalAIError, OSError, ValueError) as exc:
                if output:
                    errors[output.output_id] = str(exc)
            st.session_state[suggestions_key][job.batch_id] = suggestions
            st.session_state[request_key] = filter_request.strip()
            st.session_state[model_key] = model
            st.session_state[error_key] = errors
            st.session_state[reviewed_key] = False
            st.rerun()

        errors = st.session_state.get(error_key, {})
        for output_id, message in errors.items():
            output = _output_by_id(job, output_id)
            source = _source_by_id(job, output.source_id) if output else None
            st.warning(f"{source.original_name if source else 'Một tệp'}: {message}")

        if existing:
            st.markdown("#### Kết quả AI cần bạn xem lại")
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
                "Tôi đã đọc các gợi ý bên trên cho yêu cầu lọc hiện tại.",
                key=reviewed_key,
                disabled=not request_is_current,
            )
            if st.button(
                "Áp dụng gợi ý vào các ô chọn",
                key=f"officeflow-ai-apply-{job.batch_id}",
                disabled=not reviewed or not request_is_current,
                help="Keep được chọn; Skip bỏ chọn; Review giữ lựa chọn hiện tại. Bạn vẫn phải kiểm tra PDF và xác nhận lưu.",
            ):
                for output in job.outputs:
                    suggestion = existing.get(output.output_id)
                    if suggestion and suggestion.decision in {"keep", "skip"}:
                        st.session_state[f"officeflow-save-{job.batch_id}-{output.output_id}"] = (
                            suggestion.decision == "keep"
                        )
                st.rerun()


def _review_screen(job: BatchJob) -> None:
    st.markdown("<div class='section-kicker'>Bước 3 · Xem lại</div>", unsafe_allow_html=True)
    st.header("Duyệt PDF trước khi lưu")
    st.info("PDF vẫn nằm trong vùng tạm. Chỉ các tệp bạn chọn và xác nhận mới được lưu vào thư mục đích.")
    st.caption(f"Thư mục lưu: `{job.destination}`")
    if not job.outputs:
        st.warning("Không có PDF nào được tạo. Bạn có thể hủy lô để xóa dữ liệu tạm.")
        for source in job.sources:
            for issue in source.issues:
                _show_issue(issue)
        if st.button("Hủy lô và xóa tệp tạm", type="primary"):
            cancel_batch(job)
            st.rerun()
        return

    st.metric("PDF tạm để duyệt", len(job.outputs))
    _ai_filter_panel(job)

    st.markdown("### Danh sách kết quả")
    selected_ids: set[str] = set()
    edited_names: dict[str, str] = {}
    suggestions = st.session_state["officeflow_ai_suggestions"].get(job.batch_id, {})
    for output in job.outputs:
        source = _source_by_id(job, output.source_id)
        source_name = source.original_name if source else "Tệp nguồn"
        select_key = f"officeflow-save-{job.batch_id}-{output.output_id}"
        name_key = f"officeflow-final-{job.batch_id}-{output.output_id}"
        st.session_state.setdefault(select_key, True)
        st.session_state.setdefault(name_key, output.final_name)
        with st.container(border=True):
            file_col, name_col, save_col = st.columns([2.25, 3.5, 1.05])
            with file_col:
                st.write(source_name)
                page_info = f"{output.page_count} trang" if output.page_count is not None else "Chưa rõ số trang"
                search_info = "Có lớp chữ" if output.searchable_text else "Chưa phát hiện lớp chữ"
                st.caption(f"{page_info} · {search_info} · {OUTPUT_STATUS_LABELS[output.status]}")
            with name_col:
                st.text_input("Tên PDF khi lưu", key=name_key, help="Chỉ tên tệp, không nhập thư mục.")
            with save_col:
                st.checkbox("Lưu PDF", key=select_key)
            edited_names[output.output_id] = st.session_state[name_key]
            if st.session_state[select_key]:
                selected_ids.add(output.output_id)
            suggestion = suggestions.get(output.output_id)
            if suggestion:
                decision_label = {"keep": "Gợi ý giữ", "skip": "Gợi ý bỏ qua", "review": "Cần xem lại"}.get(
                    suggestion.decision, "Gợi ý AI"
                )
                st.caption(f"AI · {decision_label} · {suggestion.category}: {suggestion.reason}")
                action_col, _ = st.columns([1, 4])
                with action_col:
                    st.button(
                        "Dùng tên gợi ý",
                        key=f"officeflow-ai-name-{job.batch_id}-{output.output_id}",
                        on_click=_apply_ai_name,
                        args=(job.batch_id, output.output_id),
                    )
            for issue in output.issues:
                _show_issue(issue)

    resolved_names: dict[str, str] = {}
    name_error: str | None = None
    if selected_ids:
        selected_outputs = [output for output in job.outputs if output.output_id in selected_ids]
        try:
            requested = [edited_names[output.output_id] for output in selected_outputs]
            normalized = [normalize_pdf_name(name) for name in requested]
            unique_names = resolve_unique_pdf_names(normalized, job.destination)
            for output, requested_name, resolved in zip(selected_outputs, normalized, unique_names, strict=True):
                resolved_names[output.output_id] = resolved
                if resolved.casefold() != requested_name.casefold():
                    st.warning(f"`{requested_name}` bị trùng; tên lưu sẽ là `{resolved}` để tránh ghi đè.")
        except ValueError as exc:
            name_error = str(exc)
            st.error(name_error)

    st.markdown("### Bản xem trước")
    output_ids = [output.output_id for output in job.outputs]
    selected_preview_id = st.selectbox(
        "Chọn một PDF để xem",
        options=output_ids,
        format_func=lambda output_id: _preview_label(job, output_id, edited_names),
        key=f"officeflow-preview-select-{job.batch_id}",
    )
    preview_output = _output_by_id(job, selected_preview_id)
    if preview_output and preview_output.staging_path and preview_output.staging_path.is_file():
        try:
            st.pdf(
                str(preview_output.staging_path),
                height=600,
                key=f"officeflow-preview-{job.batch_id}-{preview_output.output_id}",
            )
            preview_output.status = OutputStatus.PREVIEWED
        except Exception:
            st.error("Không hiển thị được bản xem trước. Bạn vẫn có thể bỏ chọn PDF này hoặc cài lại Streamlit PDF viewer.")

    if not selected_ids:
        st.warning("Chưa chọn PDF nào để lưu. Chọn ít nhất một tệp hoặc hủy lô.")
    reviewed = st.checkbox(
        "Tôi đã kiểm tra PDF và tên các tệp được chọn.",
        key=f"officeflow-reviewed-{job.batch_id}",
        disabled=not selected_ids,
    )
    save_col, cancel_col = st.columns([2, 1])
    with save_col:
        if st.button(
            f"Xác nhận lưu {len(selected_ids)} PDF",
            type="primary",
            disabled=not selected_ids or not reviewed or bool(name_error),
            use_container_width=True,
        ):
            commit_batch(job, selected_ids, resolved_names)
            st.rerun()
    with cancel_col:
        if st.button("Hủy và xóa PDF tạm", use_container_width=True):
            cancel_batch(job)
            st.rerun()


def _preview_label(job: BatchJob, output_id: str, names: dict[str, str]) -> str:
    output = _output_by_id(job, output_id)
    if output is None:
        return "PDF"
    source = _source_by_id(job, output.source_id)
    source_name = source.original_name if source else "Tệp nguồn"
    return f"{source_name} → {names.get(output_id, output.final_name)}"


def _retry_section(job: BatchJob) -> None:
    failed_source_ids = {
        source.source_id for source in job.sources if source.status is SourceStatus.FAILED
    }
    failed_source_ids.update(
        output.source_id for output in job.outputs if output.status is OutputStatus.FAILED
    )
    retryable = [source for source in job.sources if source.source_id in failed_source_ids]
    if not retryable:
        return
    with st.expander("Thử lại các tệp lỗi"):
        st.write("Chọn lại phiên bản hiện tại; kết quả lô trước vẫn được giữ trong lịch sử.")
        for source in retryable:
            st.caption(f"• {source.original_name}")
        retry_uploads = st.file_uploader(
            "Chọn lại tệp muốn thử",
            type=["docx", "xlsx", "pptx", "pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp"],
            accept_multiple_files=True,
            key=f"officeflow-retry-uploads-{job.batch_id}",
            max_upload_size=100,
        )
        if st.button(
            "Tạo lô thử lại",
            key=f"officeflow-retry-button-{job.batch_id}",
            disabled=not retry_uploads,
        ):
            try:
                retry_job = create_retry_batch(job, retry_uploads, job.destination)
                _add_job(retry_job)
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))


def _summary_screen(job: BatchJob) -> None:
    st.markdown("<div class='section-kicker'>Kết quả lô</div>", unsafe_allow_html=True)
    st.header("Tổng kết xử lý")
    st.caption(f"Trạng thái: {BATCH_STATE_LABELS[job.state]} · Mã lô: `{job.batch_id[:8]}`")
    metrics = st.columns(4)
    metrics[0].metric("Tệp nguồn", job.source_count)
    metrics[1].metric("PDF đã lưu", job.succeeded_count)
    metrics[2].metric("Lỗi", job.failed_count)
    metrics[3].metric("Bỏ qua", job.skipped_count)
    if job.state is BatchState.CANCELLED and job.outputs and not job.succeeded_count:
        st.info("Không có PDF nào được lưu. Các PDF tạm đã bị xóa theo lựa chọn của bạn.")

    outputs_by_source = {output.source_id: output for output in job.outputs}
    for source in job.sources:
        output = outputs_by_source.get(source.source_id)
        status = OUTPUT_STATUS_LABELS[output.status] if output is not None else SOURCE_STATUS_LABELS[source.status]
        with st.container(border=True):
            st.write(f"{source.original_name} · {status}")
            if output and output.destination_path:
                st.caption(f"Đã lưu: `{output.destination_path.name}`")
            for issue in source.issues:
                _show_issue(issue)
            if output:
                for issue in output.issues:
                    _show_issue(issue)

    _retry_section(job)
    if st.button("Tạo lô mới", type="primary", use_container_width=True):
        st.session_state["officeflow_active_job"] = None
        st.rerun()
    _show_history(exclude_batch_id=job.batch_id)


def _show_history(exclude_batch_id: str | None = None) -> None:
    jobs = [job for job in st.session_state.get("officeflow_jobs", []) if job.batch_id != exclude_batch_id]
    if not jobs:
        return
    with st.expander("Lịch sử các lô trong phiên này"):
        for job in reversed(jobs):
            st.caption(
                f"{job.created_at.astimezone().strftime('%H:%M %d/%m/%Y')} · "
                f"{job.batch_id[:8]} · {BATCH_STATE_LABELS[job.state]} · "
                f"đã lưu {job.succeeded_count}, lỗi {job.failed_count}, bỏ qua {job.skipped_count}"
            )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📄", layout="wide")
    _init_session()
    cleanup_orphaned_staging_once()
    job = _active_job()
    step = 1 if job is None else 2 if job.state is BatchState.PREFLIGHT else 3
    _render_header(step)
    if job is None:
        _new_batch_screen()
    elif job.state is BatchState.PREFLIGHT:
        _preflight_screen(job)
    elif job.state in {BatchState.CONVERTING, BatchState.REVIEW}:
        _review_screen(job)
    else:
        _summary_screen(job)
    st.divider()
    st.caption("Tài liệu được xử lý cục bộ. Chỉ lưu PDF sau khi bạn xác nhận.")


if __name__ == "__main__":
    main()

# Tasks: Chuyển Office và OCR PDF/ảnh scan sang PDF

Input: Tài liệu thiết kế trong `specs/001-office-to-pdf-batch/`

Prerequisites: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/batch-conversion.md`

Automated test tasks are omitted because they were not requested. Each user story has independent manual acceptance criteria.

## Format

- [P] means the task can be done in parallel with other tasks that touch different files and have no unfinished dependency.
- [US1], [US2], [US3], and [US4] map to the stories in `spec.md`.
- Every task includes its target file path.

## Phase 1: Setup

Purpose: Create the local application skeleton, runtime configuration, and operator guide.

- [x] T001 [P] Create the Python package and Streamlit entry point in `src/officeflow/__init__.py` and `src/officeflow/app.py`.
- [x] T002 [P] Declare Python 3.12, Streamlit PDF viewer, pypdf, Pillow, OCRmyPDF, and pypdfium2 in `pyproject.toml`.
- [x] T003 [P] Bind Streamlit to 127.0.0.1 and disable usage statistics in `.streamlit/config.toml`.
- [x] T004 [P] Document LibreOffice, OCRmyPDF, Tesseract, local language packs, and supported files in `README.md`.

## Phase 2: Foundational

Purpose: Build shared models, validation, collision-safe names, staging, Office conversion, and OCR process handling.

- [x] T005 Define BatchJob, SourceFile, OutputPdf, and ConversionIssue in `src/officeflow/models.py`; preserve states `selected, preflight, converting, review, committed, cancelled, failed`, source statuses `selected, valid, converting, converted, failed, skipped`, output statuses `staged, previewed, committed, discarded, failed`, and issue codes `unsupported_type, unreadable, password_protected, conversion_failed, ocr_failed, name_conflict, destination_error, preview_warning`.
- [x] T006 [P] Implement preflight in `src/officeflow/validation.py`; allow .docx, .xlsx, .pptx, .pdf, .png, .jpg, .jpeg, .tif, .tiff, and .bmp; limit each batch to 20; reject Office legacy/macro formats, GIF, HEIC, and multi-frame TIFF.
- [x] T007 [P] Implement safe deterministic names and numeric collision suffixes against both the batch and destination in `src/officeflow/naming.py`.
- [x] T008 [P] Implement per-batch staging, atomic no-overwrite commit, cancel, and stale-folder cleanup in `src/officeflow/staging.py`.
- [x] T009 [P] Implement isolated LibreOffice PDF conversion with format-specific filters, per-file errors, and timeout in `src/officeflow/converter.py`.
- [x] T010 [P] Implement local OCRmyPDF processing with language selection, one-image-to-one-PDF behavior, existing-text skip, and timeout in `src/officeflow/ocr.py`.

Checkpoint: Shared models and local conversion/OCR adapters are ready before the user-story flows.

## Phase 3: User Story 1 - Chuyển Office thành PDF theo lô (Priority: P1)

Goal: Convert Word, Excel, and PowerPoint files to one PDF each, with isolated per-file outcomes.

Independent acceptance criteria: A mixed .docx/.xlsx/.pptx batch creates one openable PDF per valid source, keeps originals unchanged, excludes hidden slides and notes pages, and continues after one unreadable input.

- [x] T011 [US1] Map .docx, .xlsx, and .pptx to LibreOffice PDF filters in `src/officeflow/converter.py`; use print settings and exclude hidden slides/notes pages.
- [x] T012 [US1] Orchestrate per-file Office conversion, staging, and status updates in `src/officeflow/batch.py`.
- [x] T013 [US1] Build explicit multi-file selection, destination selection, progress, and per-file status UI in `src/officeflow/app.py`.

Checkpoint: User Story 1 converts Office batches and stages PDFs for review.

## Phase 4: User Story 4 - OCR PDF scan và ảnh thành PDF tìm kiếm được (Priority: P1)

Goal: Accept scanned PDFs and images, preserve visible page content, and add selectable/searchable OCR text locally.

Independent acceptance criteria: A multi-page scanned PDF and a single image each produce one openable PDF with a text layer for the chosen language; source files stay unchanged; missing language data or a broken source is reported per file.

- [x] T014 [US4] Route PDF and image sources through the OCR processor while keeping Office inputs on LibreOffice in `src/officeflow/batch.py` and `src/officeflow/ocr.py`.
- [x] T015 [US4] Add Vietnamese, English, and Vietnamese+English selection and report searchable-text warnings in `src/officeflow/app.py` and `src/officeflow/messages_vi.py`.

Checkpoint: User Story 4 produces searchable PDFs for supported scan inputs without sending data outside the device.

## Phase 5: User Story 2 - Kiểm tra tệp và tên PDF trước khi lưu (Priority: P1)

Goal: Let users review validation, names, and PDF contents before any output reaches the destination.

Independent acceptance criteria: Duplicate names resolve to distinct proposals; unsupported, unreadable, encrypted, and OCR issues are visible by file; PDFs can be previewed; cancelling removes staging and leaves the destination unchanged.

- [x] T016 [US2] Show the preflight file/type/status/issue/name table in `src/officeflow/app.py`.
- [x] T017 [US2] Allow proposed-name editing and show collision-resolved final names in `src/officeflow/app.py` using `src/officeflow/naming.py`.
- [x] T018 [US2] Preview staged PDFs and searchable-text warnings in `src/officeflow/app.py` before confirmation.
- [x] T019 [US2] Wire cancel/discard controls to remove staging in `src/officeflow/app.py` and `src/officeflow/staging.py`.

Checkpoint: User Story 2 can inspect each output and safely cancel before commit.

## Phase 6: User Story 3 - Lưu và đối chiếu kết quả của lô (Priority: P2)

Goal: Save only approved PDFs, summarize results, and retry failed inputs in a new batch.

Independent acceptance criteria: Only checked PDFs are written; the summary reports source/success/failure/skipped counts; retries preserve earlier batch summaries and never overwrite.

- [x] T020 [US3] Commit selected outputs with an atomic no-overwrite operation in `src/officeflow/staging.py` and `src/officeflow/batch.py`.
- [x] T021 [US3] Display final per-file outcomes and batch totals in `src/officeflow/app.py`.
- [x] T022 [US3] Add a new-batch retry flow for reselected failed sources in `src/officeflow/batch.py` and `src/officeflow/app.py`.

Checkpoint: User Story 3 saves reviewed outputs and reports a usable batch summary.

## Phase 7: Polish & Cross-Cutting Concerns

Purpose: Finish Vietnamese messages, operator guidance, and staging recovery.

- [x] T023 [P] Centralize Vietnamese labels and errors in `src/officeflow/messages_vi.py` and use them in `src/officeflow/app.py`.
- [x] T024 [P] Document installation, launch, supported formats, OCR language packs, and manual acceptance flow in `README.md` and `specs/001-office-to-pdf-batch/quickstart.md`.
- [x] T025 [P] Remove orphaned old staging folders without touching active or committed outputs in `src/officeflow/staging.py` and `src/officeflow/app.py`.

## Dependencies & Execution Order

- Setup tasks can run in parallel.
- Foundation starts after setup; T005 precedes model-dependent service work. T006, T007, T009, and T010 use separate modules; T008 depends on T007 for safe names.
- US1 and US4 build the two conversion paths on top of Foundation.
- US2 follows both conversion paths because review needs staged PDFs.
- US3 follows review because commit and retry require user-approved names and outputs.
- Polish can proceed after the relevant application paths exist.

## Parallel Opportunities

- Setup: T001-T004 touch separate files and can run concurrently.
- Foundation: after T005, T006, T007, T009, and T010 can be done in parallel; T008 follows T007.
- UI and integration tasks that touch `src/officeflow/app.py` should be sequenced to avoid overlapping edits.
- Documentation T024 and stale-folder cleanup T025 can proceed independently after their code prerequisites.

## Implementation Strategy

### MVP First

1. Complete setup and Foundation.
2. Complete US1 and US4 so Office and scan inputs both create staged PDFs.
3. Complete US2 for preflight, naming, preview, and cancel.
4. Complete US3 for explicit commit, summary, and retry.
5. Use the manual acceptance flows in `specs/001-office-to-pdf-batch/quickstart.md` before a pilot.

Automated test-writing tasks are omitted because they were not requested.

## Phase 8: Local AI Suggestions & Frontend Polish

Purpose: Improve the review UI and add optional local-only classification without changing the user-approved save flow.

- [x] T026 Add a responsive workflow header, clearer preflight counts, bounded selected-PDF preview, and per-file save controls in `src/officeflow/app.py`.
- [x] T027 Enforce a 500 MB aggregate batch limit and isolate unexpected per-file conversion exceptions in `src/officeflow/validation.py` and `src/officeflow/batch.py`.
- [x] T028 Implement Ollama loopback model discovery, bounded PDF text extraction, structured suggestions, and cloud/remote model rejection in `src/officeflow/ai_filter.py`.
- [x] T029 Add an opt-in AI filter panel with editable suggestions and explicit user application in `src/officeflow/app.py`.
- [ ] T030 Run manual acceptance on Windows with Python 3.12, LibreOffice, OCRmyPDF/Tesseract, and Ollama installed; record environment blockers/results in `specs/001-office-to-pdf-batch/quickstart.md`.
- [x] T031 Verify frontend package syntax and local Streamlit startup; record which optional conversion/OCR/AI runtimes are available in `specs/001-office-to-pdf-batch/quickstart.md`.

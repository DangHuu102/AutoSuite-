"""Local OCR adapter for scanned PDFs and single or merged image files."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .converter import ConversionError, ConversionResult
from .models import IssueCode
from .validation import IMAGE_EXTENSIONS

SUPPORTED_OCR_LANGUAGES = {"vie", "eng", "vie+eng"}
DEFAULT_OCR_TIMEOUT_SECONDS = 600


def find_ocrmypdf() -> str | None:
    configured = os.environ.get("OFFICEFLOW_OCRMYPDF")
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    found = shutil.which("ocrmypdf") or shutil.which("ocrmypdf.exe")
    if found:
        return found
    sibling = Path(sys.executable).with_name("ocrmypdf.exe")
    if sibling.is_file():
        return str(sibling)
    return None


def find_tesseract() -> Path | None:
    configured = os.environ.get("OFFICEFLOW_TESSERACT")
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        return Path(found).resolve()
    roots = {
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
        str(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs"),
    }
    roots.discard(None)
    for root in roots:
        candidate = Path(root) / "Tesseract-OCR" / "tesseract.exe"
        if candidate.is_file():
            return candidate
    return None


def _has_traineddata(directory: Path) -> bool:
    try:
        return directory.is_dir() and any(directory.glob("*.traineddata"))
    except OSError:
        return False


def _has_tesseract_configs(directory: Path) -> bool:
    return (directory / "configs" / "hocr").is_file() and (directory / "pdf.ttf").is_file()


def _copy_missing_tesseract_support(source_tessdata: Path, target_tessdata: Path) -> None:
    target_tessdata.mkdir(parents=True, exist_ok=True)
    for subdir in ("configs", "tessconfigs"):
        src_sub = source_tessdata / subdir
        if src_sub.is_dir():
            shutil.copytree(src_sub, target_tessdata / subdir, dirs_exist_ok=True)
    for item in source_tessdata.iterdir():
        if item.is_file() and (
            item.name == "pdf.ttf"
            or item.suffix == ".traineddata"
            or item.name.startswith("eng.user-")
        ):
            dest = target_tessdata / item.name
            if not dest.is_file():
                shutil.copyfile(item, dest)


def _resolve_tessdata_dir(
    system_tessdata: Path | None,
    language: str = "vie",
    *,
    ensure_support: bool = True,
) -> Path | None:
    candidates: list[Path] = []
    for raw in (os.environ.get("OFFICEFLOW_TESSDATA"), os.environ.get("TESSDATA_PREFIX")):
        if not raw:
            continue
        base = Path(raw).expanduser()
        nested = base / "tessdata"
        if _has_traineddata(nested):
            candidates.append(nested)
        elif _has_traineddata(base):
            candidates.append(base)
    project_tessdata = Path(__file__).resolve().parents[2] / ".tesseract" / "tessdata"
    if _has_traineddata(project_tessdata):
        candidates.append(project_tessdata)
    if system_tessdata and _has_traineddata(system_tessdata):
        candidates.append(system_tessdata)
    if not candidates:
        return None

    requested_langs = [part.strip() for part in language.split("+") if part.strip()] or ["vie"]
    chosen = next(
        (
            c
            for c in candidates
            if all((c / f"{lang}.traineddata").is_file() for lang in requested_langs)
        ),
        next((c for c in candidates if (c / "vie.traineddata").is_file()), candidates[0]),
    )
    if (
        not ensure_support
        or _has_tesseract_configs(chosen)
        or system_tessdata is None
        or not system_tessdata.is_dir()
    ):
        return chosen

    try:
        _copy_missing_tesseract_support(system_tessdata, chosen)
        if _has_tesseract_configs(chosen):
            return chosen
    except OSError:
        pass

    fallback = Path(tempfile.gettempdir()) / "officeflow-tessdata"
    if fallback.is_symlink():
        return chosen
    try:
        _copy_missing_tesseract_support(system_tessdata, fallback)
        for cand in candidates:
            for trained in cand.glob("*.traineddata"):
                dest = fallback / trained.name
                if not dest.is_file():
                    shutil.copyfile(trained, dest)
        if _has_tesseract_configs(fallback):
            return fallback
    except OSError:
        pass
    return chosen


def inspect_tessdata(language: str = "vie") -> dict[str, Any]:
    """Read-only inspection of available Tesseract traineddata and support config files."""
    tesseract_exe = find_tesseract()
    system_tessdata: Path | None = None
    if tesseract_exe is not None:
        candidate = tesseract_exe.parent / "tessdata"
        if candidate.is_dir():
            system_tessdata = candidate
    resolved = _resolve_tessdata_dir(system_tessdata, language, ensure_support=False)
    available_languages: list[str] = []
    support_ready = False
    if resolved is not None and resolved.is_dir():
        try:
            available_languages = sorted(
                {item.stem for item in resolved.glob("*.traineddata") if item.is_file()},
                key=str.casefold,
            )
            support_ready = _has_tesseract_configs(resolved)
        except OSError:
            pass
    lang_set = {lang.casefold() for lang in available_languages}
    return {
        "system_dir": str(system_tessdata) if system_tessdata else None,
        "resolved_dir": str(resolved) if resolved else None,
        "available_languages": available_languages,
        "required_languages": {
            "vie": "vie" in lang_set,
            "eng": "eng" in lang_set,
            "osd": "osd" in lang_set,
        },
        "support_files_ready": support_ready,
    }


def _build_ocr_env(language: str = "vie") -> dict[str, str]:
    env = os.environ.copy()
    tesseract_exe = find_tesseract()
    system_tessdata: Path | None = None
    if tesseract_exe is not None:
        tesseract_dir = str(tesseract_exe.parent)
        path_entries = env.get("PATH", "").split(os.pathsep)
        if not any(os.path.normcase(entry) == os.path.normcase(tesseract_dir) for entry in path_entries):
            env["PATH"] = f"{tesseract_dir}{os.pathsep}{env.get('PATH', '')}"
        candidate_tessdata = tesseract_exe.parent / "tessdata"
        if candidate_tessdata.is_dir():
            system_tessdata = candidate_tessdata

    tessdata_dir = _resolve_tessdata_dir(system_tessdata, language, ensure_support=True)
    if tessdata_dir is not None:
        env["TESSDATA_PREFIX"] = str(tessdata_dir)
    return env


def _normalize_image_to_png(source_path: Path, dest_png: Path) -> Path:
    try:
        with Image.open(source_path) as raw_image:
            source_image = ImageOps.exif_transpose(raw_image)
            source_image.load()
            if "A" in source_image.getbands() or "transparency" in source_image.info:
                rgba = source_image.convert("RGBA")
                flattened = Image.new("RGB", rgba.size, "white")
                flattened.paste(rgba, mask=rgba.getchannel("A"))
                normalized_image = flattened
            elif source_image.mode in {"1", "L", "RGB"}:
                normalized_image = source_image
            else:
                normalized_image = source_image.convert("RGB")
            normalized_image.save(dest_png, format="PNG", dpi=(300, 300))
    except (OSError, Image.DecompressionBombError, ValueError) as exc:
        raise ConversionError("Không đọc được ảnh scan.", IssueCode.UNREADABLE) from exc
    return dest_png


class OCRProcessor:
    """Create searchable PDFs locally using OCRmyPDF and Tesseract."""

    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    ) -> None:
        self.executable = executable or find_ocrmypdf()
        self.timeout_seconds = timeout_seconds
        if not self.executable:
            raise FileNotFoundError("Không tìm thấy OCRmyPDF trong môi trường Python hiện tại.")

    def _run_ocrmypdf(
        self,
        input_path: Path,
        output_path: Path,
        language: str,
        *,
        is_image_input: bool,
    ) -> ConversionResult:
        args = [
            self.executable,
            "--output-type",
            "pdf",
            "--skip-text",
            "--jobs",
            "1",
            "-l",
            language,
        ]
        if is_image_input:
            args.extend(["--image-dpi", "300"])
        args.extend([str(input_path), str(output_path)])

        try:
            process = subprocess.run(
                args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                env=_build_ocr_env(language),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionError(
                f"OCR vượt quá {self.timeout_seconds} giây; hãy thử xử lý tệp ít trang hơn.",
                IssueCode.OCR_FAILED,
            ) from exc
        except OSError as exc:
            raise ConversionError(
                "Không khởi chạy được OCRmyPDF. Kiểm tra cài đặt OCRmyPDF/Tesseract.",
                IssueCode.OCR_FAILED,
            ) from exc

        if process.returncode != 0 or not output_path.is_file():
            combined = f"{process.stderr}\n{process.stdout}".casefold()
            if (
                "failed loading language" in combined
                or "traineddata" in combined
                or "language data" in combined
            ):
                message = (
                    f"Thiếu gói ngôn ngữ OCR '{language}'. Cài gói Tesseract tương ứng rồi thử lại."
                )
            elif "encrypted" in combined or "password" in combined:
                message = "PDF được bảo vệ bằng mật khẩu; hãy lưu một bản PDF không khóa rồi thử lại."
                raise ConversionError(message, IssueCode.PASSWORD_PROTECTED)
            elif "digital signature" in combined or "signed pdf" in combined:
                message = "PDF có chữ ký số. OCR không thể giữ hiệu lực chữ ký; hãy dùng bản chưa ký."
                raise ConversionError(message, IssueCode.OCR_FAILED)
            else:
                message = (
                    "OCR không hoàn tất. Kiểm tra định dạng, ngôn ngữ Tesseract đã cài, "
                    "quyền truy cập và chất lượng scan."
                )
            raise ConversionError(message, IssueCode.OCR_FAILED)

        try:
            with output_path.open("rb") as pdf_file:
                if pdf_file.read(5) != b"%PDF-":
                    raise ConversionError("OCR tạo kết quả không phải PDF.", IssueCode.OCR_FAILED)
            reader = PdfReader(str(output_path), strict=False)
            if reader.is_encrypted:
                raise ConversionError("PDF kết quả đang bị khóa.", IssueCode.OCR_FAILED)
            page_count = len(reader.pages)
            if page_count < 1:
                raise ConversionError("PDF kết quả không có trang.", IssueCode.OCR_FAILED)
            text_length = sum(len((page.extract_text() or "").strip()) for page in reader.pages)
        except (OSError, PdfReadError, ValueError, TypeError) as exc:
            raise ConversionError("PDF tạo từ OCR không đọc được hoặc bị hỏng.", IssueCode.OCR_FAILED) from exc

        return ConversionResult(
            pdf_path=output_path,
            page_count=page_count,
            searchable_text_chars=text_length,
        )

    def process(self, source_path: Path, output_path: Path, language: str = "vie") -> ConversionResult:
        if language not in SUPPORTED_OCR_LANGUAGES:
            raise ValueError("Ngôn ngữ OCR không được hỗ trợ.")
        extension = source_path.suffix.casefold()
        if extension != ".pdf" and extension not in IMAGE_EXTENSIONS:
            raise ConversionError("OCR chỉ nhận PDF hoặc ảnh scan.", IssueCode.UNSUPPORTED_TYPE)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        input_path = source_path
        is_image = extension in IMAGE_EXTENSIONS
        if is_image:
            input_path = _normalize_image_to_png(source_path, output_path.parent / "ocr-input.png")
        return self._run_ocrmypdf(input_path, output_path, language, is_image_input=is_image)

    def merge_images_to_pdf(
        self,
        image_paths: Sequence[Path],
        output_path: Path,
        language: str = "vie",
    ) -> ConversionResult:
        """Combine one or more scan images in order into one searchable PDF with OCR."""
        if language not in SUPPORTED_OCR_LANGUAGES:
            raise ValueError("Ngôn ngữ OCR không được hỗ trợ.")
        if not image_paths:
            raise ValueError("Cần ít nhất một ảnh để ghép PDF.")
        for path in image_paths:
            if path.suffix.casefold() not in IMAGE_EXTENSIONS:
                raise ConversionError("OCR ghép ảnh chỉ nhận các định dạng ảnh scan.", IssueCode.UNSUPPORTED_TYPE)

        if len(image_paths) == 1:
            return self.process(image_paths[0], output_path, language)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="merge-", dir=output_path.parent, ignore_cleanup_errors=True
        ) as work_str:
            work_dir = Path(work_str)
            normalized_pngs: list[Path] = []
            for index, path in enumerate(image_paths, start=1):
                dest_png = work_dir / f"page-{index:04d}.png"
                normalized_pngs.append(_normalize_image_to_png(path, dest_png))

            raw_merged_pdf = work_dir / "merged-raw.pdf"
            combined = False
            try:
                import img2pdf

                with raw_merged_pdf.open("wb") as out_stream:
                    img2pdf.convert([str(p) for p in normalized_pngs], outputstream=out_stream)
                combined = raw_merged_pdf.is_file() and raw_merged_pdf.stat().st_size > 0
            except Exception:
                combined = False

            if not combined:
                opened = [Image.open(p).convert("RGB") for p in normalized_pngs]
                try:
                    opened[0].save(
                        raw_merged_pdf,
                        "PDF",
                        resolution=300.0,
                        save_all=True,
                        append_images=opened[1:],
                    )
                finally:
                    for im in opened:
                        im.close()

            return self._run_ocrmypdf(
                raw_merged_pdf, output_path, language, is_image_input=False
            )

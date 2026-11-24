"""End-to-end ASGI tests for AutoSuite's low-RAM Starlette webapp, streaming downloads, and table fidelity."""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock
import uuid
import zipfile
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from officeflow.converter import ConversionResult
import officeflow.staging as staging
import officeflow.webapp as webapp


class _AsgiResponse:
    def __init__(self, status_code: int, headers: dict[str, str], content: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


def _encode_multipart(
    fields: dict[str, str], files: list[tuple[str, str, bytes, str]]
) -> tuple[bytes, str]:
    boundary = f"----AutoSuiteBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, val in fields.items():
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{val}\r\n".encode("utf-8")
        )
    for field_name, filename, data, content_type in files:
        chunks.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _asgi_request(
    method: str,
    raw_path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    host: str = "autosuite.localhost:8501",
) -> _AsgiResponse:
    parsed = urllib.parse.urlsplit(raw_path)
    path = parsed.path or "/"
    query_string = parsed.query.encode("utf-8")

    hdr_list: list[tuple[bytes, bytes]] = [(b"host", host.encode("latin-1"))]
    if body:
        hdr_list.append((b"content-length", str(len(body)).encode("latin-1")))
    for k, v in (headers or {}).items():
        if k.lower() == "host":
            hdr_list[0] = (b"host", v.encode("latin-1"))
        else:
            hdr_list.append((k.lower().encode("latin-1"), v.encode("latin-1")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": hdr_list,
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8501),
    }

    async def _run() -> _AsgiResponse:
        sent_body = False

        async def receive() -> dict[str, Any]:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(0.05)
            return {"type": "http.disconnect"}

        status_code = 500
        resp_headers: dict[str, str] = {}
        resp_chunks: list[bytes] = []

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                for hk, hv in message.get("headers", []):
                    resp_headers[hk.decode("latin-1").lower()] = hv.decode("latin-1")
            elif message["type"] == "http.response.body":
                resp_chunks.append(message.get("body", b""))

        await webapp.app(scope, receive, send)
        return _AsgiResponse(status_code, resp_headers, b"".join(resp_chunks))

    return asyncio.run(_run())


def _build_tabular_pdf_bytes() -> bytes:
    """Create a synthetic PDF containing a 3-column financial table for PDF->Word testing."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)

    font_dict = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_bold = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
        }
    )
    font_ref = writer._add_object(font_dict)
    bold_ref = writer._add_object(font_bold)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref, NameObject("/F2"): bold_ref})}
    )

    content_ops = (
        "BT /F2 15 Tf 1 0 0 1 70 780 Tm (BANG KE CHI PHI Q4 2026) Tj ET\n"
        "BT /F2 11 Tf 1 0 0 1 70 740 Tm (STT) Tj 1 0 0 1 140 740 Tm (Hang muc) Tj 1 0 0 1 380 740 Tm (So tien VND) Tj ET\n"
        "BT /F1 11 Tf 1 0 0 1 70 718 Tm (1) Tj 1 0 0 1 140 718 Tm (Van phong pham) Tj 1 0 0 1 395 718 Tm (4,500,000) Tj ET\n"
        "BT /F1 11 Tf 1 0 0 1 70 696 Tm (2) Tj 1 0 0 1 140 696 Tm (Thue may chu VPS) Tj 1 0 0 1 388 696 Tm (12,800,000) Tj ET\n"
        "0.6 w 65 688 420 68 re S\n"
    ).encode("latin-1")
    stream = DecodedStreamObject()
    stream.set_data(content_ops)
    page[NameObject("/Contents")] = writer._add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _valid_docx_bytes(label: str = "Doc") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("word/document.xml", f"<w:document>{label}</w:document>")
    return buf.getvalue()


class _FastStubConverter:
    def convert_to_pdf(self, source_path: Path, output_dir: Path) -> ConversionResult:
        out_pdf = output_dir / f"{source_path.stem}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with out_pdf.open("wb") as handle:
            writer.write(handle)
        return ConversionResult(pdf_path=out_pdf, page_count=1)


class TestAutoSuiteWebApp(unittest.TestCase):
    def tearDown(self) -> None:
        webapp._store.clear_all()

    def test_spa_index_static_assets_and_health_endpoints(self) -> None:
        r_health = _asgi_request("GET", "/api/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.text, "ok")

        r_st_health = _asgi_request("GET", "/_stcore/health")
        self.assertEqual(r_st_health.status_code, 200)
        self.assertEqual(r_st_health.text, "ok")

        r_index = _asgi_request("GET", "/")
        self.assertEqual(r_index.status_code, 200)
        self.assertIn("AutoSuite", r_index.text)
        self.assertIn("Tự động nhận diện", r_index.text)
        self.assertNotIn("stAppDeployButton", r_index.text)
        self.assertNotIn("Số tệp tối đa", r_index.text)

        r_css = _asgi_request("GET", "/static/styles.css")
        self.assertEqual(r_css.status_code, 200)
        r_js = _asgi_request("GET", "/static/app.js")
        self.assertEqual(r_js.status_code, 200)
        self.assertIn("showSaveFilePicker", r_js.text)

    def test_dns_rebinding_and_csrf_origin_protection(self) -> None:
        r_bad_host = _asgi_request("GET", "/api/health", host="evil.attacker.com")
        self.assertEqual(r_bad_host.status_code, 403)

        r_bad_origin = _asgi_request(
            "POST",
            "/api/jobs",
            headers={"Origin": "https://evil.attacker.com"},
        )
        self.assertEqual(r_bad_origin.status_code, 403)

        r_cross_site = _asgi_request(
            "POST",
            "/api/jobs",
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(r_cross_site.status_code, 403)

    def test_pdf_to_word_end_to_end_streaming_download_and_table_preservation(self) -> None:
        pdf_bytes = _build_tabular_pdf_bytes()
        body, ctype = _encode_multipart(
            fields={"target_format": "docx", "ocr_language": "vie"},
            files=[("files", "Bang-chi-phi-Q4.pdf", pdf_bytes, "application/pdf")],
        )
        res = _asgi_request(
            "POST",
            "/api/jobs",
            headers={
                "Content-Type": ctype,
                "Origin": "http://autosuite.localhost:8501",
            },
            body=body,
        )
        self.assertEqual(res.status_code, 202)
        job_id = res.json()["job_id"]

        snap = None
        for _ in range(80):
            poll = _asgi_request("GET", f"/api/jobs/{job_id}")
            self.assertEqual(poll.status_code, 200)
            snap = poll.json()
            if snap["status"] in {"review", "failed"}:
                break
            time.sleep(0.05)

        assert snap is not None
        self.assertEqual(snap["status"], "review")
        self.assertEqual(len(snap["outputs"]), 1)
        out = snap["outputs"][0]
        self.assertGreaterEqual(out["table_count"], 1)

        # Verify preview-blocks endpoint
        prev = _asgi_request(
            "GET", f"/api/jobs/{job_id}/outputs/{out['output_id']}/preview-blocks"
        )
        self.assertEqual(prev.status_code, 200)
        blocks = prev.json()["blocks"]
        self.assertTrue(any(b["type"] == "table" for b in blocks))

        # Verify MP4-downloader-style HTTP attachment download with Vietnamese UTF-8 filename
        custom_vn_name = "Báo cáo chi phí Q4.docx"
        dl = _asgi_request(
            "GET",
            f"/api/jobs/{job_id}/download?output_id={out['output_id']}&name={urllib.parse.quote(custom_vn_name)}",
        )
        self.assertEqual(dl.status_code, 200)
        cdisp = dl.headers.get("content-disposition", "")
        self.assertIn("attachment;", cdisp)
        self.assertIn('filename="Bao cao chi phi Q4.docx"', cdisp)
        self.assertIn("filename*=UTF-8''B%C3%A1o%20c%C3%A1o%20chi%20ph%C3%AD%20Q4.docx", cdisp)
        self.assertEqual(dl.headers.get("accept-ranges"), "bytes")
        self.assertEqual(dl.headers.get("x-content-type-options"), "nosniff")

        with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
            names = set(zf.namelist())
            self.assertIn("word/document.xml", names)
            self.assertIn("word/styles.xml", names)
            doc_xml = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("<w:tbl>", doc_xml)
            self.assertIn("<w:rFonts", doc_xml)
            self.assertIn("4,500,000", doc_xml)

        # Delete job and confirm 404 afterward
        rm = _asgi_request(
            "DELETE",
            f"/api/jobs/{job_id}",
            headers={"Origin": "http://autosuite.localhost:8501"},
        )
        self.assertEqual(rm.status_code, 200)
        self.assertEqual(_asgi_request("GET", f"/api/jobs/{job_id}").status_code, 404)

    def test_multi_file_pdf_batch_rename_zip_stream_and_inline_view(self) -> None:
        with (
            mock.patch("officeflow.converter.find_libreoffice", return_value="soffice"),
            mock.patch("officeflow.converter.LibreOfficeConverter", return_value=_FastStubConverter()),
        ):
            body, ctype = _encode_multipart(
                fields={"target_format": "pdf", "ocr_language": "vie"},
                files=[
                    ("files", "Tai-lieu-1.docx", _valid_docx_bytes("1"), "application/octet-stream"),
                    ("files", "Tai-lieu-2.docx", _valid_docx_bytes("2"), "application/octet-stream"),
                ],
            )
            res = _asgi_request("POST", "/api/jobs", headers={"Content-Type": ctype}, body=body)
            self.assertEqual(res.status_code, 202)
            job_id = res.json()["job_id"]

            snap = None
            for _ in range(80):
                snap = _asgi_request("GET", f"/api/jobs/{job_id}").json()
                if snap["status"] in {"review", "failed"}:
                    break
                time.sleep(0.05)

            assert snap is not None
            self.assertEqual(snap["status"], "review")
            self.assertEqual(len(snap["outputs"]), 2)
            out1, out2 = snap["outputs"]

            # Patch duplicate custom names -> backend resolves collision automatically
            patch_body = json.dumps(
                {
                    "names": {out1["output_id"]: "Hồ sơ.pdf", out2["output_id"]: "Hồ sơ.pdf"},
                    "selected_ids": [out1["output_id"], out2["output_id"]],
                }
            ).encode("utf-8")
            patched = _asgi_request(
                "PATCH",
                f"/api/jobs/{job_id}/outputs",
                headers={"Content-Type": "application/json"},
                body=patch_body,
            )
            self.assertEqual(patched.status_code, 200)

            # Inline PDF preview stream
            inline_res = _asgi_request(
                "GET", f"/api/jobs/{job_id}/outputs/{out1['output_id']}/view"
            )
            self.assertEqual(inline_res.status_code, 200)
            self.assertIn("inline;", inline_res.headers.get("content-disposition", ""))
            self.assertTrue(inline_res.content.startswith(b"%PDF"))

            # Download ZIP stream & verify temp .bundle-*.zip was unlinked by BackgroundTask
            zip_res = _asgi_request("GET", f"/api/jobs/{job_id}/download-zip")
            self.assertEqual(zip_res.status_code, 200)
            self.assertEqual(zip_res.headers.get("content-type"), "application/zip")
            with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
                self.assertEqual(sorted(zf.namelist()), ["Hồ sơ (1).pdf", "Hồ sơ.pdf"])

            rec = webapp._store.get(job_id)
            assert rec is not None and rec.job.staging_dir is not None
            self.assertEqual(list(rec.job.staging_dir.glob(".bundle-*.zip")), [])

            # Audit CSV & JSON report endpoints (never leak server temp C:\Users\... paths)
            csv_res = _asgi_request("GET", f"/api/jobs/{job_id}/report.csv")
            self.assertEqual(csv_res.status_code, 200)
            self.assertTrue(csv_res.content.startswith(b"\xef\xbb\xbf"))

            json_res = _asgi_request("GET", f"/api/jobs/{job_id}/report.json")
            self.assertEqual(json_res.status_code, 200)
            self.assertEqual(json_res.json()["destination"], "browser-download")

    def test_store_source_stream_enforces_max_bytes_and_cleans_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            with mock.patch.object(staging, "STAGING_ROOT", fake_root):
                batch_dir = staging.create_batch_staging("streamtest")
                oversized_stream = io.BytesIO(b"x" * (128 * 1024))
                with self.assertRaises(OverflowError):
                    staging.store_source_stream(
                        batch_dir,
                        "src1",
                        "big.pdf",
                        oversized_stream,
                        max_bytes=64 * 1024,
                    )
                self.assertEqual(list((batch_dir / "input").iterdir()), [])


if __name__ == "__main__":
    unittest.main()

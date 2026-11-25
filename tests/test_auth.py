"""End-to-end ASGI tests for AutoSuite Authentication, Sign Up, Cookie Sessions, History, and RBAC."""

from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.parse
from typing import Any

import officeflow.auth as auth
import officeflow.webapp as webapp
from tests.test_webapp import _build_tabular_pdf_bytes, _encode_multipart


class _AsgiAuthResponse:
    def __init__(
        self,
        status_code: int,
        headers: dict[str, str],
        set_cookies: list[str],
        content: bytes,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self.set_cookies = set_cookies
        self.content = content

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def cookie_value(self, name: str) -> str | None:
        for raw in self.set_cookies:
            jar = SimpleCookie()
            jar.load(raw)
            if name in jar:
                return jar[name].value
        return None


def _req(
    method: str,
    raw_path: str,
    *,
    json_body: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    cookie_token: str | None = None,
) -> _AsgiAuthResponse:
    parsed = urllib.parse.urlsplit(raw_path)
    path = parsed.path or "/"
    query_string = parsed.query.encode("utf-8")

    body = raw_body if raw_body is not None else (
        json.dumps(json_body).encode("utf-8") if json_body is not None else b""
    )
    hdrs: list[tuple[bytes, bytes]] = [
        (b"host", b"autosuite.localhost:8501"),
        (b"origin", b"http://autosuite.localhost:8501"),
    ]
    if body:
        hdrs.append((b"content-length", str(len(body)).encode("latin-1")))
        ct = content_type or "application/json"
        hdrs.append((b"content-type", ct.encode("latin-1")))
    if cookie_token:
        hdrs.append((b"cookie", f"{auth.COOKIE_NAME}={cookie_token}".encode("latin-1")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": hdrs,
        "client": ("127.0.0.1", 55555),
        "server": ("127.0.0.1", 8501),
    }

    async def _run() -> _AsgiAuthResponse:
        sent = False

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(0.05)
            return {"type": "http.disconnect"}

        status_code = 500
        resp_headers: dict[str, str] = {}
        set_cookies: list[str] = []
        chunks: list[bytes] = []

        async def send(msg: dict[str, Any]) -> None:
            nonlocal status_code
            if msg["type"] == "http.response.start":
                status_code = int(msg["status"])
                for hk, hv in msg.get("headers", []):
                    k = hk.decode("latin-1").lower()
                    v = hv.decode("latin-1")
                    if k == "set-cookie":
                        set_cookies.append(v)
                    else:
                        resp_headers[k] = v
            elif msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))

        await webapp.app(scope, receive, send)
        return _AsgiAuthResponse(status_code, resp_headers, set_cookies, b"".join(chunks))

    return asyncio.run(_run())


class TestAuthAndRBAC(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("OFFICEFLOW_DB_PATH")
        self._old_secret = os.environ.get("OFFICEFLOW_SESSION_SECRET")
        os.environ["OFFICEFLOW_DB_PATH"] = str(Path(self._tmp.name) / "test_auth.db")
        os.environ["OFFICEFLOW_SESSION_SECRET"] = "test-secret-key-at-least-32-chars-long-0001"
        webapp._auth_service = None

    def tearDown(self) -> None:
        webapp._store.clear_all()
        webapp._auth_service = None
        if self._old_db is None:
            os.environ.pop("OFFICEFLOW_DB_PATH", None)
        else:
            os.environ["OFFICEFLOW_DB_PATH"] = self._old_db
        if self._old_secret is None:
            os.environ.pop("OFFICEFLOW_SESSION_SECRET", None)
        else:
            os.environ["OFFICEFLOW_SESSION_SECRET"] = self._old_secret
        self._tmp.cleanup()

    def test_register_validation_login_cookie_and_rbac_401_vs_403(self) -> None:
        # 1. Unauthenticated checks
        me_guest = _req("GET", "/api/auth/me")
        self.assertEqual(me_guest.status_code, 200)
        self.assertFalse(me_guest.json()["authenticated"])

        self.assertEqual(_req("GET", "/api/account/history").status_code, 401)
        self.assertEqual(_req("GET", "/api/admin/users").status_code, 401)

        # 2. InputModel validation errors
        bad_reg = _req(
            "POST",
            "/api/auth/register",
            json_body={
                "username": "ab",
                "email": "not-an-email",
                "password": "123",
                "confirm_password": "456",
            },
        )
        self.assertEqual(bad_reg.status_code, 400)
        fe = bad_reg.json()["field_errors"]
        self.assertIn("username", fe)
        self.assertIn("email", fe)
        self.assertIn("password", fe)
        self.assertIn("confirm_password", fe)

        # 3. First user registered becomes Admin automatically & receives HttpOnly cookie
        reg_admin = _req(
            "POST",
            "/api/auth/register",
            json_body={
                "username": "Admin AutoSuite",
                "email": "admin@autosuite.local",
                "password": "Password123",
                "confirm_password": "Password123",
            },
        )
        self.assertEqual(reg_admin.status_code, 201)
        admin_data = reg_admin.json()["user"]
        self.assertEqual(admin_data["role"], "Admin")
        self.assertNotIn("password_hash", admin_data)
        self.assertTrue(any("httponly" in c.lower() for c in reg_admin.set_cookies))
        admin_token = reg_admin.cookie_value(auth.COOKIE_NAME)
        self.assertIsNotNone(admin_token)

        # 4. Duplicate email rejected cleanly
        dup = _req(
            "POST",
            "/api/auth/register",
            json_body={
                "username": "Another Name",
                "email": "ADMIN@autosuite.local",
                "password": "Password123",
                "confirm_password": "Password123",
            },
        )
        self.assertEqual(dup.status_code, 400)
        self.assertIn("email", dup.json()["field_errors"])

        # 5. Second user becomes regular User
        reg_user = _req(
            "POST",
            "/api/auth/register",
            json_body={
                "username": "Nguyen Van B",
                "email": "user@autosuite.local",
                "password": "UserPass99",
                "confirm_password": "UserPass99",
            },
        )
        self.assertEqual(reg_user.status_code, 201)
        user_data = reg_user.json()["user"]
        self.assertEqual(user_data["role"], "User")
        user_token = reg_user.cookie_value(auth.COOKIE_NAME)
        self.assertIsNotNone(user_token)

        # 6. Role-based Authorization: Regular User gets 403 Forbidden on /api/admin/users
        forbidden = _req("GET", "/api/admin/users", cookie_token=user_token)
        self.assertEqual(forbidden.status_code, 403)

        # Admin gets 200 OK with both users
        admin_list = _req("GET", "/api/admin/users", cookie_token=admin_token)
        self.assertEqual(admin_list.status_code, 200)
        self.assertEqual(len(admin_list.json()["users"]), 2)

        # 7. Admin cannot demote the sole remaining Admin
        demote_self = _req(
            "PATCH",
            f"/api/admin/users/{admin_data['id']}/role",
            json_body={"role": "User"},
            cookie_token=admin_token,
        )
        self.assertEqual(demote_self.status_code, 400)

        # Admin promotes User -> Admin, then can demote back
        promo = _req(
            "PATCH",
            f"/api/admin/users/{user_data['id']}/role",
            json_body={"role": "Admin"},
            cookie_token=admin_token,
        )
        self.assertEqual(promo.status_code, 200)
        self.assertEqual(promo.json()["user"]["role"], "Admin")

        # 8. Login + Change Password + Logout
        bad_login = _req(
            "POST",
            "/api/auth/login",
            json_body={"identifier": "user@autosuite.local", "password": "WrongPassword"},
        )
        self.assertEqual(bad_login.status_code, 401)

        chpw = _req(
            "POST",
            "/api/account/password",
            json_body={
                "current_password": "UserPass99",
                "new_password": "NewSecurePass2026",
                "confirm_password": "NewSecurePass2026",
            },
            cookie_token=user_token,
        )
        self.assertEqual(chpw.status_code, 200)

        ok_login = _req(
            "POST",
            "/api/auth/login",
            json_body={
                "identifier": "Nguyen Van B",
                "password": "NewSecurePass2026",
                "remember_me": True,
            },
        )
        self.assertEqual(ok_login.status_code, 200)
        self.assertTrue(any("max-age=604800" in c.lower() for c in ok_login.set_cookies))

        logout_res = _req("POST", "/api/auth/logout", cookie_token=user_token)
        self.assertEqual(logout_res.status_code, 200)
        self.assertTrue(any("max-age=0" in c.lower() for c in logout_res.set_cookies))

    def test_signed_in_user_conversion_saves_personal_history(self) -> None:
        reg = _req(
            "POST",
            "/api/auth/register",
            json_body={
                "username": "Tran Minh",
                "email": "minh@autosuite.local",
                "password": "Password123",
                "confirm_password": "Password123",
            },
        )
        self.assertEqual(reg.status_code, 201)
        token = reg.cookie_value(auth.COOKIE_NAME)

        body, ctype = _encode_multipart(
            fields={"target_format": "docx", "ocr_language": "vie"},
            files=[("files", "Bang-luong.pdf", _build_tabular_pdf_bytes(), "application/pdf")],
        )
        job_res = _req(
            "POST",
            "/api/jobs",
            raw_body=body,
            content_type=ctype,
            cookie_token=token,
        )
        self.assertEqual(job_res.status_code, 202)
        job_id = job_res.json()["job_id"]

        for _ in range(80):
            snap = _req("GET", f"/api/jobs/{job_id}", cookie_token=token).json()
            if snap["status"] in {"review", "failed"}:
                break
            time.sleep(0.05)

        hist = _req("GET", "/api/account/history", cookie_token=token)
        self.assertEqual(hist.status_code, 200)
        items = hist.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["target_format"], "docx")
        self.assertIn("Bang-luong.docx", items[0]["summary_names"])

        # Delete history entry
        del_h = _req("DELETE", f"/api/account/history/{items[0]['id']}", cookie_token=token)
        self.assertEqual(del_h.status_code, 200)
        self.assertTrue(del_h.json()["deleted"])
        self.assertEqual(len(_req("GET", "/api/account/history", cookie_token=token).json()["items"]), 0)


if __name__ == "__main__":
    unittest.main()

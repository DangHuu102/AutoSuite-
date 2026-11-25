"""Layered Authentication, Authorization (RBAC), and User History module for AutoSuite.

Follows clean layered MVC principles:
- Domain Models: UserEntity, ConversionHistoryEntity
- Input Models (DTOs with validation): RegisterInputModel, LoginInputModel, ChangePasswordInputModel
- View Models: UserViewModel (never exposes password hashes)
- Repository: AuthRepository (SQLite WAL, zero external DB dependencies, < 2 MB RAM)
- Service + Cookie Auth: scrypt password hashing + HMAC-SHA256 signed HttpOnly cookies
  with Sliding Expiration (2 hours default, 7 days with Remember Me).
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Any

COOKIE_NAME = "autosuite_session"
SESSION_TTL_DEFAULT = 2 * 60 * 60       # 2 hours (matches sliding cookie convention)
SESSION_TTL_REMEMBER = 7 * 24 * 60 * 60 # 7 days when Remember Me is checked
VALID_ROLES = frozenset({"User", "Admin"})

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_USERNAME_RE = re.compile(r"^[\w.\-\u00C0-\u1EF9 ]{3,40}$", re.UNICODE)


def _default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "OfficeFlow"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / "officeflow"


def resolve_db_path() -> Path:
    custom = os.environ.get("OFFICEFLOW_DB_PATH", "").strip()
    if custom:
        return Path(custom).expanduser()
    return _default_data_dir() / "autosuite.db"


# ---------------------------------------------------------------------------
# 1. Domain Models & View Models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UserEntity:
    id: int
    username: str
    email: str
    password_hash: str
    role: str
    created_at: str


@dataclass(slots=True)
class UserViewModel:
    id: int
    username: str
    email: str
    role: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at,
        }

    @classmethod
    def from_entity(cls, entity: UserEntity) -> "UserViewModel":
        return cls(
            id=entity.id,
            username=entity.username,
            email=entity.email,
            role=entity.role,
            created_at=entity.created_at,
        )


@dataclass(slots=True)
class ConversionHistoryEntity:
    id: int
    user_id: int
    job_id: str
    target_format: str
    file_count: int
    summary_names: str
    total_bytes: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "target_format": self.target_format,
            "file_count": self.file_count,
            "summary_names": self.summary_names,
            "total_bytes": self.total_bytes,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# 2. Input Models (Binding & Validation DTOs)
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Carries field-level validation errors similar to ASP.NET ModelState."""

    def __init__(self, message: str, field_errors: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.field_errors = field_errors or {}


@dataclass(slots=True)
class RegisterInputModel:
    username: str
    email: str
    password: str
    confirm_password: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegisterInputModel":
        username = str(data.get("username") or "").strip()
        email = str(data.get("email") or "").strip().lower()
        password = str(data.get("password") or "")
        confirm = str(data.get("confirm_password") or "")

        errors: dict[str, str] = {}
        if not username:
            errors["username"] = "Vui lòng nhập tên người dùng."
        elif len(username) < 3 or len(username) > 40:
            errors["username"] = "Tên người dùng phải từ 3 đến 40 ký tự."
        elif not _USERNAME_RE.match(username):
            errors["username"] = "Tên người dùng chỉ gồm chữ, số, dấu cách, gạch ngang hoặc gạch dưới."

        if not email:
            errors["email"] = "Vui lòng nhập địa chỉ email."
        elif len(email) > 120 or not _EMAIL_RE.match(email):
            errors["email"] = "Địa chỉ email không hợp lệ."

        if not password:
            errors["password"] = "Vui lòng nhập mật khẩu."
        elif len(password) < 6 or len(password) > 100:
            errors["password"] = "Mật khẩu phải từ 6 đến 100 ký tự."

        if confirm != password:
            errors["confirm_password"] = "Mật khẩu xác nhận không khớp."

        if errors:
            first_msg = next(iter(errors.values()))
            raise ValidationError(first_msg, errors)

        return cls(
            username=username,
            email=email,
            password=password,
            confirm_password=confirm,
        )


@dataclass(slots=True)
class LoginInputModel:
    identifier: str  # Email or Username
    password: str
    remember_me: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoginInputModel":
        identifier = str(data.get("identifier") or data.get("email") or data.get("username") or "").strip()
        password = str(data.get("password") or "")
        remember_me = bool(data.get("remember_me", False))

        errors: dict[str, str] = {}
        if not identifier:
            errors["identifier"] = "Vui lòng nhập Email hoặc tên người dùng."
        if not password:
            errors["password"] = "Vui lòng nhập mật khẩu."
        if errors:
            raise ValidationError(next(iter(errors.values())), errors)

        return cls(identifier=identifier, password=password, remember_me=remember_me)


@dataclass(slots=True)
class ChangePasswordInputModel:
    current_password: str
    new_password: str
    confirm_password: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChangePasswordInputModel":
        cur = str(data.get("current_password") or "")
        new = str(data.get("new_password") or "")
        confirm = str(data.get("confirm_password") or "")

        errors: dict[str, str] = {}
        if not cur:
            errors["current_password"] = "Vui lòng nhập mật khẩu hiện tại."
        if len(new) < 6 or len(new) > 100:
            errors["new_password"] = "Mật khẩu mới phải từ 6 đến 100 ký tự."
        if confirm != new:
            errors["confirm_password"] = "Xác nhận mật khẩu mới không khớp."
        if errors:
            raise ValidationError(next(iter(errors.values())), errors)

        return cls(current_password=cur, new_password=new, confirm_password=confirm)


# ---------------------------------------------------------------------------
# 3. Password Hashing & Signed Session Cookie Engine
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash password with scrypt + 16-byte random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify plaintext password against stored scrypt hash in constant time."""
    try:
        scheme, salt_hex, digest_hex = stored_hash.split("$", 2)
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(val: str) -> bytes:
    pad = "=" * ((4 - len(val) % 4) % 4)
    return base64.urlsafe_b64decode(val + pad)


class SessionTokenManager:
    """Sign and verify HttpOnly session cookies with sliding expiration."""

    def __init__(self, secret_path: Path) -> None:
        self._secret_path = secret_path
        self._secret: bytes | None = None
        self._lock = threading.Lock()

    def _get_secret(self) -> bytes:
        env_secret = os.environ.get("OFFICEFLOW_SESSION_SECRET", "").strip()
        if env_secret:
            return env_secret.encode("utf-8")
        with self._lock:
            if self._secret is not None:
                return self._secret
            self._secret_path.parent.mkdir(parents=True, exist_ok=True)
            if self._secret_path.is_file():
                raw = self._secret_path.read_text(encoding="utf-8").strip()
                if len(raw) >= 32:
                    self._secret = raw.encode("utf-8")
                    return self._secret
            generated = secrets.token_hex(32)
            try:
                self._secret_path.write_text(generated, encoding="utf-8")
            except OSError:
                pass
            self._secret = generated.encode("utf-8")
            return self._secret

    def create_token(
        self, user_id: int, role: str, *, remember_me: bool = False
    ) -> tuple[str, int]:
        now = int(time.time())
        ttl = SESSION_TTL_REMEMBER if remember_me else SESSION_TTL_DEFAULT
        payload = {
            "uid": int(user_id),
            "role": role,
            "rem": bool(remember_me),
            "iat": now,
            "exp": now + ttl,
        }
        body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = _b64url_encode(
            hmac.new(self._get_secret(), body.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{body}.{sig}", ttl

    def verify_token(self, token: str) -> tuple[dict[str, Any] | None, bool]:
        """Return (payload, needs_sliding_refresh) if valid, else (None, False)."""
        if not token or "." not in token:
            return None, False
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None, False
        body, sig = parts
        expected_sig = _b64url_encode(
            hmac.new(self._get_secret(), body.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected_sig):
            return None, False
        try:
            payload = json.loads(_b64url_decode(body).decode("utf-8"))
        except Exception:
            return None, False
        if not isinstance(payload, dict):
            return None, False
        now = int(time.time())
        exp = int(payload.get("exp") or 0)
        iat = int(payload.get("iat") or 0)
        if exp <= now or not payload.get("uid"):
            return None, False
        total_ttl = max(exp - iat, 60)
        elapsed = now - iat
        needs_refresh = elapsed >= (total_ttl * 0.25)
        return payload, needs_refresh


# ---------------------------------------------------------------------------
# 4. SQLite Repository & Auth Service
# ---------------------------------------------------------------------------


class AuthRepository:
    """Lightweight SQLite data access layer for Users and Conversion History."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._init_lock = threading.Lock()
        self._initialized_path: Path | None = None

    @property
    def db_path(self) -> Path:
        return self._db_path if self._db_path is not None else resolve_db_path()

    @contextmanager
    def _connect(self):
        path = self.db_path
        self._ensure_schema(path)
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self, path: Path) -> None:
        if self._initialized_path == path and path.is_file():
            return
        with self._init_lock:
            if self._initialized_path == path and path.is_file():
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), timeout=10.0)
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA foreign_keys = ON")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL,
                        username_lower TEXT NOT NULL UNIQUE,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'User',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS conversion_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        job_id TEXT NOT NULL,
                        target_format TEXT NOT NULL,
                        file_count INTEGER NOT NULL DEFAULT 1,
                        summary_names TEXT NOT NULL,
                        total_bytes INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_history_user_created
                    ON conversion_history(user_id, id DESC);
                    """
                )
                conn.commit()
            finally:
                conn.close()
            self._initialized_path = path

    @staticmethod
    def _row_to_user(row: sqlite3.Row | None) -> UserEntity | None:
        if row is None:
            return None
        return UserEntity(
            id=int(row["id"]),
            username=str(row["username"]),
            email=str(row["email"]),
            password_hash=str(row["password_hash"]),
            role=str(row["role"]),
            created_at=str(row["created_at"]),
        )

    def count_users(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
            return int(row["cnt"]) if row else 0

    def count_admins(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'Admin'").fetchone()
            return int(row["cnt"]) if row else 0

    def get_user_by_id(self, user_id: int) -> UserEntity | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            return self._row_to_user(row)

    def get_user_by_identifier(self, identifier: str) -> UserEntity | None:
        key = identifier.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ? OR username_lower = ?",
                (key, key),
            ).fetchone()
            return self._row_to_user(row)

    def create_user(
        self, username: str, email: str, password_hash: str, role: str
    ) -> UserEntity:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users (username, username_lower, email, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, username.lower(), email.lower(), password_hash, role, created_at),
            )
            conn.commit()
            uid = int(cur.lastrowid)
        return UserEntity(
            id=uid,
            username=username,
            email=email.lower(),
            password_hash=password_hash,
            role=role,
            created_at=created_at,
        )

    def update_password_hash(self, user_id: int, new_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_hash, int(user_id)),
            )
            conn.commit()

    def list_users(self) -> list[UserEntity]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
            return [u for row in rows if (u := self._row_to_user(row)) is not None]

    def update_user_role(self, user_id: int, role: str) -> UserEntity | None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, int(user_id)))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            return self._row_to_user(row)

    def delete_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM users WHERE id = ?", (int(user_id),))
            conn.commit()
            return cur.rowcount > 0

    def add_history(
        self,
        user_id: int,
        job_id: str,
        target_format: str,
        file_count: int,
        summary_names: str,
        total_bytes: int,
    ) -> ConversionHistoryEntity:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO conversion_history
                    (user_id, job_id, target_format, file_count, summary_names, total_bytes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    job_id,
                    target_format,
                    int(file_count),
                    summary_names[:300],
                    int(total_bytes),
                    created_at,
                ),
            )
            # Keep latest 100 history rows per user so SQLite stays tiny
            conn.execute(
                """
                DELETE FROM conversion_history
                WHERE user_id = ? AND id NOT IN (
                    SELECT id FROM conversion_history
                    WHERE user_id = ? ORDER BY id DESC LIMIT 100
                )
                """,
                (int(user_id), int(user_id)),
            )
            conn.commit()
            hid = int(cur.lastrowid)
        return ConversionHistoryEntity(
            id=hid,
            user_id=int(user_id),
            job_id=job_id,
            target_format=target_format,
            file_count=int(file_count),
            summary_names=summary_names[:300],
            total_bytes=int(total_bytes),
            created_at=created_at,
        )

    def list_history(self, user_id: int, limit: int = 50) -> list[ConversionHistoryEntity]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversion_history
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(user_id), int(limit)),
            ).fetchall()
            return [
                ConversionHistoryEntity(
                    id=int(r["id"]),
                    user_id=int(r["user_id"]),
                    job_id=str(r["job_id"]),
                    target_format=str(r["target_format"]),
                    file_count=int(r["file_count"]),
                    summary_names=str(r["summary_names"]),
                    total_bytes=int(r["total_bytes"]),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]

    def delete_history_item(self, user_id: int, history_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM conversion_history WHERE id = ? AND user_id = ?",
                (int(history_id), int(user_id)),
            )
            conn.commit()
            return cur.rowcount > 0


class AuthService:
    """Application Service orchestrating registration, login, RBAC, and rate limiting."""

    def __init__(self, repo: AuthRepository | None = None) -> None:
        self.repo = repo or AuthRepository()
        self._tokens: SessionTokenManager | None = None
        self._failed_attempts: dict[str, list[float]] = {}
        self._rate_lock = threading.Lock()

    @property
    def tokens(self) -> SessionTokenManager:
        secret_file = self.repo.db_path.with_name(".session_secret")
        if self._tokens is None or self._tokens._secret_path != secret_file:
            self._tokens = SessionTokenManager(secret_file)
        return self._tokens

    def _check_rate_limit(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - 300.0
        with self._rate_lock:
            attempts = [t for t in self._failed_attempts.get(key, []) if t > cutoff]
            self._failed_attempts[key] = attempts
            if len(attempts) >= 10:
                raise ValidationError(
                    "Bạn đã thử đăng nhập sai quá nhiều lần. Vui lòng thử lại sau 5 phút."
                )

    def _record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            self._failed_attempts.setdefault(key, []).append(now)

    def _clear_failures(self, key: str) -> None:
        with self._rate_lock:
            self._failed_attempts.pop(key, None)

    def register(self, dto: RegisterInputModel) -> tuple[UserViewModel, str, int]:
        # First registered account automatically becomes Admin for out-of-the-box RBAC testing
        assigned_role = "Admin" if self.repo.count_users() == 0 else "User"
        pw_hash = hash_password(dto.password)
        try:
            user = self.repo.create_user(dto.username, dto.email, pw_hash, assigned_role)
        except sqlite3.IntegrityError as exc:
            msg = str(exc).lower()
            if "email" in msg:
                raise ValidationError(
                    "Email này đã được đăng ký.", {"email": "Email này đã được đăng ký."}
                ) from exc
            if "username" in msg:
                raise ValidationError(
                    "Tên người dùng này đã tồn tại.",
                    {"username": "Tên người dùng này đã tồn tại."},
                ) from exc
            raise ValidationError("Tài khoản đã tồn tại.") from exc

        token, ttl = self.tokens.create_token(user.id, user.role, remember_me=False)
        return UserViewModel.from_entity(user), token, ttl

    def login(self, dto: LoginInputModel, client_key: str = "local") -> tuple[UserViewModel, str, int]:
        rate_key = f"{client_key}:{dto.identifier.lower()}"
        self._check_rate_limit(rate_key)

        user = self.repo.get_user_by_identifier(dto.identifier)
        if user is None or not verify_password(dto.password, user.password_hash):
            self._record_failure(rate_key)
            raise ValidationError("Email/tên đăng nhập hoặc mật khẩu không đúng.")

        self._clear_failures(rate_key)
        token, ttl = self.tokens.create_token(
            user.id, user.role, remember_me=dto.remember_me
        )
        return UserViewModel.from_entity(user), token, ttl

    def authenticate_cookie(
        self, cookie_value: str | None
    ) -> tuple[UserViewModel | None, tuple[str, int] | None]:
        """Validate session cookie against DB and return (user, refreshed_cookie_or_None)."""
        if not cookie_value:
            return None, None
        payload, needs_refresh = self.tokens.verify_token(cookie_value)
        if payload is None:
            return None, None
        user = self.repo.get_user_by_id(int(payload["uid"]))
        if user is None:
            return None, None
        refreshed: tuple[str, int] | None = None
        if needs_refresh or payload.get("role") != user.role:
            refreshed = self.tokens.create_token(
                user.id, user.role, remember_me=bool(payload.get("rem", False))
            )
        return UserViewModel.from_entity(user), refreshed

    def change_password(self, user_id: int, dto: ChangePasswordInputModel) -> None:
        user = self.repo.get_user_by_id(user_id)
        if user is None:
            raise ValidationError("Không tìm thấy tài khoản.")
        if not verify_password(dto.current_password, user.password_hash):
            raise ValidationError(
                "Mật khẩu hiện tại không đúng.",
                {"current_password": "Mật khẩu hiện tại không đúng."},
            )
        self.repo.update_password_hash(user.id, hash_password(dto.new_password))

    def set_user_role(self, actor_id: int, target_user_id: int, new_role: str) -> UserViewModel:
        if new_role not in VALID_ROLES:
            raise ValidationError("Vai trò không hợp lệ (chỉ nhận 'Admin' hoặc 'User').")
        target = self.repo.get_user_by_id(target_user_id)
        if target is None:
            raise LookupError("Không tìm thấy người dùng.")
        if target.role == "Admin" and new_role != "Admin" and self.repo.count_admins() <= 1:
            raise ValidationError("Không thể hạ quyền Quản trị viên duy nhất của hệ thống.")
        updated = self.repo.update_user_role(target_user_id, new_role)
        if updated is None:
            raise LookupError("Không tìm thấy người dùng.")
        return UserViewModel.from_entity(updated)

    def delete_user(self, actor_id: int, target_user_id: int) -> bool:
        if actor_id == target_user_id:
            raise ValidationError("Bạn không thể tự xóa tài khoản đang đăng nhập.")
        target = self.repo.get_user_by_id(target_user_id)
        if target is None:
            raise LookupError("Không tìm thấy người dùng.")
        if target.role == "Admin" and self.repo.count_admins() <= 1:
            raise ValidationError("Không thể xóa Quản trị viên duy nhất của hệ thống.")
        return self.repo.delete_user(target_user_id)

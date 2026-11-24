"""Open the local AutoSuite interface in a native Windows webview window."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    directory = base / "OfficeFlow" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "desktop-server.log"


def _wait_until_ready(process: subprocess.Popen, url: str, timeout: float = 25.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.05)
    return False


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[2]


def _run_bundled_server() -> int:
    """Re-enter the bundled executable as a lightweight Uvicorn server worker."""
    port = 8501
    for index, argument in enumerate(sys.argv[2:], start=2):
        if argument.startswith("--port=") or argument.startswith("--server.port="):
            port = int(argument.partition("=")[2])
        elif argument in {"--port", "--server.port"} and index + 1 < len(sys.argv):
            port = int(sys.argv[index + 1])

    import uvicorn

    uvicorn.run(
        "officeflow.webapp:app",
        host="127.0.0.1",
        port=port,
        workers=1,
        ws="none",
        timeout_keep_alive=5,
        timeout_graceful_shutdown=10,
        limit_concurrency=32,
        access_log=False,
        log_level="warning",
    )
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--officeflow-server":
        return _run_bundled_server()

    try:
        import webview
    except ImportError:
        print(
            "Thiếu giao diện desktop. Cài AutoSuite bằng: uv pip install -e \".[desktop]\"",
            file=sys.stderr,
        )
        return 1

    project_root = _project_root()
    port = _free_local_port()
    url = f"http://127.0.0.1:{port}"
    health_url = f"{url}/api/health"
    log_path = _log_path()
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if getattr(sys, "frozen", False):
        server_command = [sys.executable, "--officeflow-server", f"--port={port}"]
    else:
        server_command = [
            sys.executable,
            "-m",
            "uvicorn",
            "officeflow.webapp:app",
            "--app-dir",
            str(project_root / "src"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
            "--timeout-keep-alive",
            "5",
            "--timeout-graceful-shutdown",
            "10",
            "--limit-concurrency",
            "32",
            "--no-access-log",
        ]

    log_file = log_path.open("a", encoding="utf-8")
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(
            server_command,
            cwd=project_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        if not _wait_until_ready(process, health_url):
            print(
                f"AutoSuite chưa khởi động được. Xem nhật ký tại: {log_path}",
                file=sys.stderr,
            )
            return 1
        if hasattr(webview, "settings") and isinstance(webview.settings, dict):
            webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(
            "AutoSuite — Chuyển đổi PDF & Word",
            url,
            width=1120,
            height=780,
            min_size=(880, 620),
            background_color="#f5f7fc",
        )
        try:
            webview.start(debug=False)
        except (RuntimeError, OSError) as exc:
            print(
                f"Không mở được cửa sổ desktop: {exc}. Hãy cài Microsoft Edge WebView2 Runtime.",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())

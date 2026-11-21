"""Open the local OfficeFlow interface in a native Windows webview window."""

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


def _wait_until_ready(process: subprocess.Popen, url: str, timeout: float = 45.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=1.5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    return False


def _application_paths() -> tuple[Path, Path]:
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS"))
        return bundle_root / "officeflow" / "app.py", bundle_root
    app_path = Path(__file__).with_name("app.py").resolve()
    return app_path, Path(__file__).resolve().parents[2]


def _run_bundled_server() -> int:
    """Re-enter the bundled executable as a Streamlit server worker."""
    port = "8501"
    for index, argument in enumerate(sys.argv[2:], start=2):
        if argument.startswith("--server.port="):
            port = argument.partition("=")[2]
        elif argument == "--server.port" and index + 1 < len(sys.argv):
            port = sys.argv[index + 1]
    app_path, _ = _application_paths()
    if not app_path.is_file():
        print(f"Không tìm thấy giao diện Streamlit trong gói: {app_path}", file=sys.stderr)
        return 1
    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--server.maxUploadSize=100",
        "--browser.gatherUsageStats=false",
    ]
    from streamlit.web import cli as streamlit_cli

    try:
        streamlit_cli.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--officeflow-server":
        return _run_bundled_server()

    try:
        import webview
    except ImportError:
        print(
            "Thiếu giao diện desktop. Cài OfficeFlow bằng: uv pip install -e \".[desktop]\"",
            file=sys.stderr,
        )
        return 1

    app_path, project_root = _application_paths()
    port = _free_local_port()
    url = f"http://127.0.0.1:{port}"
    health_url = f"{url}/_stcore/health"
    log_path = _log_path()
    log_file = log_path.open("a", encoding="utf-8")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if getattr(sys, "frozen", False):
        server_command = [sys.executable, "--officeflow-server", f"--server.port={port}"]
    else:
        server_command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--server.maxUploadSize=100",
            "--browser.gatherUsageStats=false",
        ]
    process = subprocess.Popen(
        server_command,
        cwd=project_root,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )
    try:
        if not _wait_until_ready(process, health_url):
            print(
                f"OfficeFlow chưa khởi động được. Xem nhật ký tại: {log_path}",
                file=sys.stderr,
            )
            return 1
        if hasattr(webview, "settings") and isinstance(webview.settings, dict):
            webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(
            "OfficeFlow",
            url,
            width=1120,
            height=780,
            min_size=(900, 650),
            background_color="#f7f9fd",
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
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())

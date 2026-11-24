"""Self-healing 24/7 background service runner for AutoSuite on Windows."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8501
HEALTH_URL = f"http://127.0.0.1:{PORT}/api/health"


def _is_healthy() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(HEALTH_URL, timeout=1.5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _log_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    directory = base / "OfficeFlow" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def run_forever() -> int:
    """Keep the lightweight AutoSuite Uvicorn server running on 127.0.0.1:8501 and auto-restart on crash."""
    project_root = Path(__file__).resolve().parents[2]
    src_dir = project_root / "src"
    log_file_path = _log_dir() / "autosuite-24x7.log"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "officeflow.webapp:app",
        "--app-dir",
        str(src_dir),
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
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

    process: subprocess.Popen | None = None
    while True:
        if _is_healthy():
            time.sleep(5.0)
            continue

        if process is not None and process.poll() is None:
            time.sleep(1.5)
            continue

        with log_file_path.open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                cmd,
                cwd=project_root,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

        for _ in range(40):
            if _is_healthy() or (process is not None and process.poll() is not None):
                break
            time.sleep(0.25)
        time.sleep(2.0)


def spawn_detached() -> int:
    """Spawn the 24/7 watchdog in a completely detached background process and register Windows Startup."""
    project_root = Path(__file__).resolve().parents[2]
    script_path = Path(__file__).resolve()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    runner_exe = str(pythonw if pythonw.is_file() else Path(sys.executable))

    appdata = os.environ.get("APPDATA")
    if appdata:
        startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if startup_dir.is_dir():
            vbs_path = startup_dir / "AutoSuite-24x7.vbs"
            vbs_content = (
                'Set WshShell = CreateObject("WScript.Shell")\n'
                f'WshShell.CurrentDirectory = "{project_root}"\n'
                f'WshShell.Run """{runner_exe}"" ""{script_path}"" --worker", 0, False\n'
            )
            try:
                vbs_path.write_text(vbs_content, encoding="utf-8")
            except OSError:
                pass

    if not _is_healthy():
        flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
        env = os.environ.copy()
        src_path = str(project_root / "src")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_path
        subprocess.Popen(
            [runner_exe, "-m", "officeflow.daemon_24x7", "--worker"],
            cwd=project_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
        for _ in range(40):
            if _is_healthy():
                break
            time.sleep(0.25)

    try:
        webbrowser.open(f"http://autosuite.localhost:{PORT}")
    except Exception:
        pass
    print("AutoSuite 24/7 service is active at: http://autosuite.localhost:8501")
    return 0


def main() -> int:
    if "--worker" in sys.argv:
        return run_forever()
    return spawn_detached()


if __name__ == "__main__":
    raise SystemExit(main())

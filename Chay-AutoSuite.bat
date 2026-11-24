@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Đang kiểm tra / khởi động AutoSuite tại http://autosuite.localhost:8501 ...
".\.venv\Scripts\python.exe" -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/api/health', timeout=1.2).status == 200 else 1)" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Dịch vụ AutoSuite 24/24 đang hoạt động sẵn. Đang mở trình duyệt...
    start "" "http://autosuite.localhost:8501"
    exit /b 0
)
start "" /b cmd /c "timeout /t 1 /nobreak >nul & start "" "http://autosuite.localhost:8501""
".\.venv\Scripts\python.exe" -m uvicorn officeflow.webapp:app --app-dir src --host 127.0.0.1 --port 8501 --workers 1 --timeout-keep-alive 5 --timeout-graceful-shutdown 10 --limit-concurrency 32 --no-access-log

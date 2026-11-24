@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Đang kích hoạt dịch vụ AutoSuite chạy ngầm 24/24 và tự khởi động cùng Windows...
".\.venv\Scripts\python.exe" -m officeflow.daemon_24x7
echo [OK] AutoSuite đã chạy ngầm 24/24 tại: http://autosuite.localhost:8501

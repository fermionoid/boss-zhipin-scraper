@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
"%~dp0python\python.exe" "%~dp0scraper\updater.py"
"%~dp0python\python.exe" "%~dp0scraper\main.py"
pause
endlocal

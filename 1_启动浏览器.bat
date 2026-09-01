@echo off
setlocal

taskkill /F /IM brave.exe >nul 2>&1

set "BROWSER_EXE="
if exist "%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe" set "BROWSER_EXE=%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"
if not defined BROWSER_EXE if exist "%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe" set "BROWSER_EXE=%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"
if not defined BROWSER_EXE if exist "%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe"
if not defined BROWSER_EXE if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_EXE if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_EXE if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER_EXE if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER_EXE if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER_EXE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

if not defined BROWSER_EXE (
    echo Brave, Chrome, or Edge was not found.
    pause
    exit /b 1
)

start "" "%BROWSER_EXE%" --remote-debugging-port=9222 --user-data-dir="%~dp0browser_profile" "https://www.zhipin.com/web/chat/index"
echo Browser started. Log in and stay on the chat page.
endlocal

@echo off
title QQ Bot Launcher

REM ============================================================
REM  QQ Bot one-click launcher
REM  1. Start bot.py (bot service + WebUI on port 8080)
REM  2. Start NapCat (auto login via NAPCAT_QQ env var)
REM
REM  Note: launcher.bat -q has a known argv forwarding bug
REM  (NapCatQQ Issue #1477). napcat.mjs is patched to read the
REM  NAPCAT_QQ env var for quick login instead.
REM  Admin rights required (NapCat DLL injection).
REM ============================================================

REM Elevate to admin if needed
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c set NAPCAT_QQ=3896608979&& cd /d \"%~dp0\" && \"%~f0\"' -Verb runAs"
    exit /b
)

set ROOT=%~dp0
set NAPCAT_DIR=%ROOT%NapCat\NapCat.Shell
set NAPCAT_QQ=3896608979

echo.
echo [1/2] Starting bot.py (service + WebUI on port 8080) ...
cd /d "%ROOT%"
start "QQ-Bot" /min python bot.py

timeout /t 4 /nobreak >nul

echo [2/3] Starting watchdog (auto-restart bot if it dies) ...
start "Watchdog" /min python watchdog.py

timeout /t 2 /nobreak >nul

echo [3/3] Starting NapCat (auto login QQ %NAPCAT_QQ%) ...
cd /d "%NAPCAT_DIR%"
set NAPCAT_QQ=%NAPCAT_QQ%
start "NapCat" cmd /c "launcher.bat"

echo.
echo ================================================
echo   Started!
echo   - WebUI console:  http://127.0.0.1:8080/
echo   - NapCat:         auto login QQ %NAPCAT_QQ% (no QR scan)
echo                     (scan once only if credentials expired)
echo   - To stop:        close "NapCat" and "QQ-Bot" windows
echo ================================================
echo.
pause

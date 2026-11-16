@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python start.py %*
) else (
    py -3 start.py %*
)
set "LAB_EXIT_CODE=%ERRORLEVEL%"
if not "%LAB_EXIT_CODE%"=="0" pause
exit /b %LAB_EXIT_CODE%

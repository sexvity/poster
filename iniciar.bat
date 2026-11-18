@echo off
cd /d "%~dp0"
rem Opens YTK without a console window (the loading screen appears in the app itself).
where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw launcher.pyw
) else (
    python launcher.pyw
)
exit

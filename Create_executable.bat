@echo off
setlocal

cd /d "%~dp0"

powershell -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Failed to build PSCADResultsAnalysis.exe.
    pause
)

exit /b %EXIT_CODE%

@echo off
setlocal
cd /d "%~dp0"

set "PROJECT_PYTHON=%~dp0..\.conda\pscad-results-analysis\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo.
    echo Project conda environment was not found:
    echo   ..\.conda\pscad-results-analysis
    echo Create it from this app folder:
    echo   conda env create --prefix ..\.conda\pscad-results-analysis -f environment.yml
    pause
    exit /b 1
)

"%PROJECT_PYTHON%" -m results_analysis_app
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo Failed to start PSCAD Results Analysis.
    pause
)

exit /b %EXIT_CODE%

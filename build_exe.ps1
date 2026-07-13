$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ProjectPython = Join-Path $PSScriptRoot "..\.conda\pscad-results-analysis\python.exe"
if (-not (Test-Path $ProjectPython)) {
    throw "Project conda environment was not found: ..\.conda\pscad-results-analysis. Create it with: conda env create --prefix ..\.conda\pscad-results-analysis -f environment.yml"
}

& $ProjectPython -c "import PyInstaller, PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, pandas, openpyxl, docx, win32com.client, matplotlib, numpy, pyexpat"

& $ProjectPython -m PyInstaller `
    --noconfirm `
    --clean `
    PSCADResultsAnalysis.spec

$exe = Join-Path $PSScriptRoot "dist\PSCADResultsAnalysis.exe"
if (-not (Test-Path $exe)) {
    throw "One-file executable was not found: $exe"
}

& $exe --smoke

Write-Host ""
Write-Host "One-file executable created:"
Write-Host "  $exe"

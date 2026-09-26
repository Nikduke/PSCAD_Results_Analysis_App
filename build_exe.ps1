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

$smokeProcess = Start-Process -FilePath $exe -ArgumentList @('--smoke') -PassThru
try {
    Wait-Process -Id $smokeProcess.Id -Timeout 30 -ErrorAction Stop | Out-Null
}
catch {
    if (-not $smokeProcess.HasExited) {
        Stop-Process -Id $smokeProcess.Id -Force -ErrorAction SilentlyContinue
    }
    throw "Executable smoke test timed out or failed to exit: $exe"
}
if ($smokeProcess.ExitCode -ne 0) {
    throw "Executable smoke test failed with exit code $($smokeProcess.ExitCode): $exe"
}

Write-Host ""
Write-Host "One-file executable created:"
Write-Host "  $exe"

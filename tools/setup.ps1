Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath $projectPython)) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Python environment failed. Install 64-bit Python 3.11 or newer.' }
    }
    & $projectPython -m pip install -r requirements-dev.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $projectPython -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'DALE installation failed.' }
    Write-Output 'DALE is ready. Double-click run.cmd to start the desktop editor.'
}
finally {
    Pop-Location
}

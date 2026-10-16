@echo off
setlocal
pushd "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\setup.ps1"
    if errorlevel 1 (
        echo DALE setup failed. See the error above.
        pause
        popd
        exit /b 1
    )
)
start "DALE" ".venv\Scripts\pythonw.exe" -m dale
popd

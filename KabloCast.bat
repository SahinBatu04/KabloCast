@echo off
setlocal
cd /d "%~dp0"
if exist "KabloCast.exe" (
    start "" "%~dp0KabloCast.exe"
) else if exist "backend\.venv\Scripts\pythonw.exe" (
    start "" "backend\.venv\Scripts\pythonw.exe" "launch_kablocast.py"
) else if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" "launch_kablocast.py"
) else (
    python "launch_kablocast.py"
)
endlocal

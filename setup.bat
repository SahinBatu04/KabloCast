@echo off
setlocal
cd /d "%~dp0"

echo [KabloCast] Checking Python environment...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12+ is required and must be in PATH.
    exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
    echo [KabloCast] Creating backend virtual environment...
    python -m venv "backend\.venv"
    if errorlevel 1 exit /b 1
)

echo [KabloCast] Installing backend dependencies...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip >nul
"backend\.venv\Scripts\python.exe" -m pip install -e "backend[dev]"
if errorlevel 1 exit /b 1

where npm >nul 2>&1
if not errorlevel 1 (
    echo [KabloCast] Installing frontend dependencies and building SPA...
    pushd frontend
    call npm install
    if errorlevel 1 (
        popd
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        popd
        exit /b 1
    )
    popd
) else (
    echo [INFO] npm not found; skipping frontend rebuild ^(prebuilt frontend/dist will be used^).
)

echo [KabloCast] Building single-click KabloCast.exe launcher...
call "%~dp0build_exe.bat"
if errorlevel 1 exit /b 1

echo.
echo [OK] KabloCast setup complete! Double-click KabloCast.exe to launch.
endlocal

@echo off
setlocal
cd /d "%~dp0"

set "CSC_EXE=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC_EXE%" (
    set "CSC_EXE=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)
if not exist "%CSC_EXE%" (
    echo [ERROR] .NET Framework csc.exe compiler was not found.
    exit /b 1
)

if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" "scripts\generate_icon.py"
    if errorlevel 1 exit /b 1
)

set "ICON_ARG="
if exist "assets\kablocast.ico" (
    set "ICON_ARG=/win32icon:assets\kablocast.ico"
)

echo [KabloCast] Compiling native KabloCast.exe...
"%CSC_EXE%" /nologo /target:winexe /optimize+ /r:System.Windows.Forms.dll %ICON_ARG% /out:KabloCast.exe "launcher\KabloCastLauncher.cs"
if errorlevel 1 exit /b 1

echo [OK] Built KabloCast.exe successfully.
endlocal

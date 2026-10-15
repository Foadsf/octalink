@echo off
setlocal
cd /d "%~dp0"

:: Auto-detect GCC from MSYS2 / MinGW if not already in PATH
where gcc >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "C:\msys64\ucrt64\bin\gcc.exe" (
        set "PATH=%PATH%;C:\msys64\ucrt64\bin"
    ) else if exist "C:\msys64\mingw64\bin\gcc.exe" (
        set "PATH=%PATH%;C:\msys64\mingw64\bin"
    )
)

set "OCTALINK_RUNTIME=python"
if defined OCTALINK_PYTHON set "OCTALINK_RUNTIME=%OCTALINK_PYTHON%"
if exist "%~dp0.venv\Scripts\python.exe" set "OCTALINK_RUNTIME=%~dp0.venv\Scripts\python.exe"
"%OCTALINK_RUNTIME%" "%~dp0octalink_gui.py" %*
set "OCTALINK_EXIT=%ERRORLEVEL%"
exit /b %OCTALINK_EXIT%
endlocal

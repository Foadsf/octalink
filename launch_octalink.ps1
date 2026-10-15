<#
.SYNOPSIS
    Launches the OctaLink Visual Block Diagram Modeling Environment.
.DESCRIPTION
    Sets up the toolchain environment (MSYS2 GCC for embedded C compilation)
    and starts the PyQt6 GUI application.
#>

param(
    [string]$ModelPath = ""
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Ensure GCC is available if installed under MSYS2
if (-not (Get-Command gcc -ErrorAction SilentlyContinue)) {
    if (Test-Path "C:\msys64\ucrt64\bin\gcc.exe") {
        $env:PATH = $env:PATH + ";" + "C:\msys64\ucrt64\bin"
    } elseif (Test-Path "C:\msys64\mingw64\bin\gcc.exe") {
        $env:PATH = $env:PATH + ";" + "C:\msys64\mingw64\bin"
    }
}

$guiScript = Join-Path $scriptDir "octalink_gui.py"
$pythonCommand = if ($env:OCTALINK_PYTHON) { $env:OCTALINK_PYTHON } else { 'python' }
$venvPython = Join-Path $scriptDir '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $pythonCommand = $venvPython }

if ($ModelPath) {
    & $pythonCommand $guiScript $ModelPath
} else {
    & $pythonCommand $guiScript
}
exit $LASTEXITCODE

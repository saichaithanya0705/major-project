param(
    [string]$PythonCommand
)

$ErrorActionPreference = "Stop"

if (-not $PythonCommand) {
    $PythonCommand = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $PythonCommand -PathType Leaf)) {
        $legacyPython = Join-Path $PSScriptRoot ".venv-1\Scripts\python.exe"
        if (Test-Path -LiteralPath $legacyPython -PathType Leaf) {
            $PythonCommand = $legacyPython
        }
    }
}

$python = Get-Command $PythonCommand -CommandType Application -ErrorAction SilentlyContinue
if (-not $python) {
    throw "[dev] Python not found: $PythonCommand. Run .\setup.ps1 first, or pass -PythonCommand with your environment's python.exe path."
}

# app.py starts the UI after the server is ready and owns its process cleanup.
# Keep both services in this terminal so Ctrl+C reaches the app's shutdown path.
$previousAutoLaunch = $env:JARVIS_AUTO_LAUNCH_ELECTRON
Push-Location $PSScriptRoot
try {
    $env:JARVIS_AUTO_LAUNCH_ELECTRON = "1"
    Write-Host "[dev] Starting app.py and the JARVIS UI. Press Ctrl+C to stop."
    & $python.Source -u app.py
    $appExitCode = $LASTEXITCODE
}
finally {
    $env:JARVIS_AUTO_LAUNCH_ELECTRON = $previousAutoLaunch
    Pop-Location
}

exit $appExitCode

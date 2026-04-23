param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

function Invoke-Step {
    param(
        [string]$Message,
        [scriptblock]$Action
    )

    Write-Host "[setup] $Message"
    & $Action
}

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

Require-Command $PythonCommand
Require-Command "npm"

$versionOutput = & $PythonCommand -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$versionParts = $versionOutput.Trim().Split(".")
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    throw "[setup] Python >= 3.11 required (found $versionOutput)."
}

Write-Host "[setup] Using Python $versionOutput"

if (-not (Test-Path $venvDir)) {
    Invoke-Step "Creating project virtual environment at $venvDir" {
        & $PythonCommand -m venv $venvDir
    }
}

if (-not (Test-Path $venvPython)) {
    throw "[setup] Virtual environment was created, but $venvPython was not found."
}

Invoke-Step "Upgrading pip inside the virtual environment..." {
    & $venvPython -m pip install --upgrade pip
}

$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) {
    Invoke-Step "Creating .env with placeholder keys..." {
@'
GEMINI_API_KEY="YOUR_API_KEY"

ELEVENLABS_URL="YOUR_API_KEY"
ELEVENLABS_API_KEY="YOUR_API_KEY"
'@ | Set-Content -Path $envPath -Encoding UTF8
    }
}

Invoke-Step "Installing Python dependencies..." {
    & $venvPython -m pip install -r (Join-Path $root "requirements.txt")
}

Invoke-Step "Installing Playwright browsers..." {
    & $venvPython -m playwright install chromium
}

Invoke-Step "Clearing Python bytecode cache..." {
    Get-ChildItem -Path $root -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Push-Location (Join-Path $root "ui")
try {
    Invoke-Step "Installing UI dependencies..." {
        npm install
    }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $root "agents\cua_cli\gemini-cli")
try {
    Invoke-Step "Installing Gemini CLI dependencies..." {
        npm install
    }
    Invoke-Step "Building Gemini CLI..." {
        npm run build
    }
}
finally {
    Pop-Location
}

Write-Host "[setup] Done."
Write-Host "[setup] Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "[setup] Then run: .\.venv\Scripts\python.exe app.py"

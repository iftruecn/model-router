# Model Router — Cross-platform installer for Windows
# Usage: .\install.ps1
#    or: powershell -ExecutionPolicy Bypass -File install.ps1

param(
    [switch]$SkipVenv,
    [switch]$DevOnly
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Model Router v1.0.1 — Windows Installer" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# Detect Python
$Python = $null
$PyVersion = ""

# Try python first, then python3
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $major, $minor = $ver.Split('.')
            if ([int]$major -ge 3 -and [int]$minor -ge 10) {
                $Python = $cmd
                $PyVersion = $ver
                break
            }
        }
    } catch {}
}

if (-not $Python) {
    Write-Host "ERROR: Python 3.10+ required. Current: ${PyVersion:-not found}" -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Python:"
    Write-Host "  1. Download from: https://www.python.org/downloads/"
    Write-Host "  2. Or: winget install Python.Python.3.11"
    Write-Host "  3. Or: scoop install python"
    exit 1
}

Write-Host "Python $PyVersion found: $Python" -ForegroundColor Green

# Create virtual environment
$VenvDir = ".venv"
if (-not $SkipVenv -and -not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    & $Python -m venv $VenvDir
}

# Activate venv
if (-not $SkipVenv -and (Test-Path "$VenvDir\Scripts\Activate.ps1")) {
    & "$VenvDir\Scripts\Activate.ps1"
    Write-Host "Virtual env activated: $VenvDir" -ForegroundColor Green
    $Python = "python"  # Use venv python
}

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow

# Upgrade pip first
& $Python -m pip install --upgrade pip --quiet

if ($DevOnly) {
    & $Python -m pip install -e ".[dev]" --quiet
} else {
    # Windows: winloop instead of uvloop (handled by pyproject.toml)
    & $Python -m pip install -e ".[all]" --quiet
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Installation failed" -ForegroundColor Red
    exit 1
}

Write-Host "winloop installed (Windows uvloop alternative)" -ForegroundColor Green

# Copy config example
if (-not (Test-Path "config.yaml") -and (Test-Path "config.example.yaml")) {
    Copy-Item "config.example.yaml" "config.yaml"
    Write-Host "Created config.yaml from example — please add your API keys!" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit config.yaml — add your API keys"
Write-Host "  2. Run: python -m model_router"
Write-Host "  3. Open: http://127.0.0.1:6060/docs"
Write-Host ""
Write-Host "Or activate venv first:"
Write-Host "  .\.venv\Scripts\Activate.ps1"

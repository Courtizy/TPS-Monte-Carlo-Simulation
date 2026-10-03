<#
  render.ps1 - Build the brand assets and render the PNG images (Windows PowerShell).

  Run from anywhere:
      powershell -ExecutionPolicy Bypass -File .\brand\render.ps1

  What it does:
    1. Finds Python (the "py" launcher or "python").
    2. Creates brand\.venv the first time, so nothing is installed system-wide.
    3. Installs Playwright and its Chromium browser (first run only).
    4. Runs build.py (CSS, JS, tokens, SVG icons), then render.py
       (favicons, README banners, social previews).

  Needs internet on the first run (packages) and every run (Google Fonts).
  Add -Clean to rebuild the virtual environment from scratch.
#>
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# Probe a native command without PowerShell 5.1 turning its stderr into an error.
function Test-Native([scriptblock]$Block) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $out = & $Block 2>$null; return @{ Ok = ($LASTEXITCODE -eq 0); Out = $out } }
    catch { return @{ Ok = $false; Out = $null } }
    finally { $ErrorActionPreference = $old }
}
$BrandDir = $PSScriptRoot
$VenvDir  = Join-Path $BrandDir ".venv"
$VenvPy   = Join-Path $VenvDir "Scripts\python.exe"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# 1. Find Python 3.9+
Step "Finding Python"
$python = $null
foreach ($candidate in @("py", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $probe = Test-Native { & $candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" }
        $version = "$($probe.Out)".Trim()
        if ($probe.Ok -and $version -match '^\d+\.\d+$' -and [version]$version -ge [version]"3.9") {
            $python = $candidate
            break
        }
    }
}
if (-not $python) {
    Write-Host "Python 3.9 or newer wasn't found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Red
    exit 1
}
Write-Host "Using $python ($version)"

# 2. Virtual environment
if ($Clean -and (Test-Path $VenvDir)) {
    Step "Removing old virtual environment"
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $VenvPy)) {
    Step "Creating virtual environment in brand\.venv"
    & $python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Couldn't create the virtual environment." }
}

# 3. Playwright + Chromium (skipped once installed)
if (-not (Test-Native { & $VenvPy -c "import playwright, pytest" }).Ok) {
    Step "Installing Playwright (first run only)"
    & $VenvPy -m pip install --quiet --upgrade pip
    & $VenvPy -m pip install --quiet playwright pytest
    if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
}
Step "Making sure Chromium is installed"
& $VenvPy -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw "Playwright couldn't install Chromium." }

# 4. Build, test, render
Push-Location $BrandDir
try {
    Step "Building CSS, JS, tokens and SVG icons"
    & $VenvPy build.py
    if ($LASTEXITCODE -ne 0) { throw "build.py failed." }

    Step "Checking the palette"
    & $VenvPy -m pytest -q test_palette.py
    if ($LASTEXITCODE -ne 0) { throw "Palette tests failed; fix palette.py before rendering." }

    Step "Rendering favicons, README banners and social previews"
    & $VenvPy render.py
    if ($LASTEXITCODE -ne 0) { throw "render.py failed (it needs internet to load the fonts)." }
}
finally {
    Pop-Location
}

Write-Host "`nDone. Images are in:" -ForegroundColor Green
Write-Host "  $(Join-Path $BrandDir 'icons')"
Write-Host "  $(Join-Path $BrandDir 'banners')"

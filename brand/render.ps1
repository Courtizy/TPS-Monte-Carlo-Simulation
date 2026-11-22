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

# 1. Find the newest Python 3.9+ (3.10+ strongly preferred: Playwright's
#    greenlet dependency no longer ships ready-made Windows builds for 3.9).
Step "Finding Python"
$python = $null; $pyArgs = @(); $version = $null
$candidates = @(
    @("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3.10"),
    @("python"), @("py"), @("python3")
)
foreach ($c in $candidates) {
    $exe = $c[0]; $extra = @($c | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $probe = Test-Native { & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" }
    $v = "$($probe.Out)".Trim()
    if ($probe.Ok -and $v -match '^\d+\.\d+$' -and [version]$v -ge [version]"3.9") {
        if (-not $version -or [version]$v -gt [version]$version) { $python = $exe; $pyArgs = $extra; $version = $v }
    }
}
if (-not $python) {
    Write-Host "Python 3.10 or newer wasn't found. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Red
    exit 1
}
Write-Host "Using $python $($pyArgs -join ' ') (Python $version)"
$oldPython = [version]$version -lt [version]"3.10"
if ($oldPython) {
    Write-Host "Python $version is past end-of-life. This will try a workaround, but installing Python 3.12 is the reliable fix." -ForegroundColor Yellow
}

# 2. Virtual environment (rebuilt automatically if it was made with a different Python)
if ((Test-Path $VenvPy) -and -not $Clean) {
    $venvVer = "$((Test-Native { & $VenvPy -c "import sys; print('%d.%d' % sys.version_info[:2])" }).Out)".Trim()
    if ($venvVer -ne $version) {
        Write-Host "brand\.venv uses Python $venvVer; rebuilding it with $version." -ForegroundColor Yellow
        $Clean = $true
    }
}
if ($Clean -and (Test-Path $VenvDir)) {
    Step "Removing old virtual environment"
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $VenvPy)) {
    Step "Creating virtual environment in brand\.venv"
    & $python @pyArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Couldn't create the virtual environment." }
}

# 3. Playwright + pytest (skipped once installed). Ready-made packages only,
#    so nothing needs a C++ compiler.
if (-not (Test-Native { & $VenvPy -c "import playwright, pytest" }).Ok) {
    Step "Installing Playwright (first run only)"
    & $VenvPy -m pip install --quiet --upgrade pip
    $pkgs = @("playwright", "pytest")
    if ($oldPython) { $pkgs = @("greenlet==3.1.1") + $pkgs }   # last greenlet with Windows builds for 3.9
    & $VenvPy -m pip install --quiet --only-binary=greenlet @pkgs
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed. Install Python 3.12 from https://www.python.org/downloads/, then run: powershell -ExecutionPolicy Bypass -File .\brand\render.ps1 -Clean"
    }
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

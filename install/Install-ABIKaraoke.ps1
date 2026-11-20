#Requires -Version 5.1
<#
    One-click setup for ABI Karaoke on Windows.

    Installs Python, FFmpeg, the app and its GUI, downloads the speech model,
    and creates a desktop shortcut.  Run it from a normal PowerShell window;
    it only asks for administrator rights if winget needs them.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\ABIKaraoke",
    [string]$Model = "base",
    [switch]$SkipModel,
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Write-Ok($message) {
    Write-Host "    $message" -ForegroundColor Green
}

function Write-Warn2($message) {
    Write-Host "    $message" -ForegroundColor Yellow
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Install-WingetPackage($id, $friendly) {
    if (-not (Test-Command "winget")) {
        throw "winget is not available. Install '$friendly' manually, then re-run this script."
    }
    Write-Host "    Installing $friendly via winget..."
    winget install --id $id --silent --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "winget returned $LASTEXITCODE for $friendly; checking whether it is usable anyway."
    }
}

Write-Host "ABI Karaoke setup" -ForegroundColor White
Write-Host "Target folder: $InstallDir"

# ---------------------------------------------------------------- Python
Write-Step "Checking Python"
$python = $null
foreach ($candidate in @("py -3.11", "py -3", "python")) {
    $parts = $candidate.Split(" ")
    if (Test-Command $parts[0]) {
        try {
            $version = & $parts[0] $parts[1..($parts.Length - 1)] -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($version -and [version]$version -ge [version]"3.10") {
                $python = $candidate
                Write-Ok "Found Python $version ($candidate)"
                break
            }
        } catch { }
    }
}
if (-not $python) {
    Install-WingetPackage "Python.Python.3.11" "Python 3.11"
    $python = "py -3.11"
    if (-not (Test-Command "py")) {
        $python = "python"
    }
    Write-Ok "Python installed"
}

# ---------------------------------------------------------------- FFmpeg
Write-Step "Checking FFmpeg"
if (Test-Command "ffmpeg") {
    Write-Ok "FFmpeg already available"
} else {
    Install-WingetPackage "Gyan.FFmpeg" "FFmpeg"
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Test-Command "ffmpeg")) {
        Write-Warn2 "FFmpeg was installed but is not on PATH yet. Close this window and run the script again."
    }
}

# ---------------------------------------------------------------- app files
Write-Step "Copying application files"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourceRoot = Split-Path -Parent $scriptRoot
if (-not (Test-Path (Join-Path $sourceRoot "abikaraoke"))) {
    throw "Cannot find the 'abikaraoke' folder next to this script. Run setup from inside the repository."
}
robocopy $sourceRoot $InstallDir /E /NFL /NDL /NJH /NJS /XD .git __pycache__ .pytest_cache outputs | Out-Null
Write-Ok "Files copied to $InstallDir"

# ---------------------------------------------------------------- venv
Write-Step "Creating a private Python environment"
$venv = Join-Path $InstallDir ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $pyParts = $python.Split(" ")
    & $pyParts[0] $pyParts[1..($pyParts.Length - 1)] -m venv $venv
}
if (-not (Test-Path $venvPython)) {
    throw "Could not create the virtual environment."
}
Write-Ok "Environment ready"

Write-Step "Installing the app and desktop UI"
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install --quiet -e "$InstallDir[gui]"
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed. Scroll up for the error."
}
Write-Ok "Installed"

# ---------------------------------------------------------------- model
if (-not $SkipModel) {
    Write-Step "Downloading the speech model (one time, ~140 MB)"
    try {
        & $venvPython -m abikaraoke setup --model $Model
        Write-Ok "Model ready"
    } catch {
        Write-Warn2 "Model download failed: $_"
        Write-Warn2 "You can retry later with: abikaraoke setup"
    }
}

# ---------------------------------------------------------------- launcher
Write-Step "Creating the launcher"
$bat = Join-Path $InstallDir "ABI Karaoke.bat"
@"
@echo off
cd /d "$InstallDir"
"$venvPython" -m abikaraoke gui %*
if errorlevel 1 pause
"@ | Set-Content -Path $bat -Encoding ASCII
Write-Ok "Launcher: $bat"

if (-not $NoShortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "ABI Karaoke.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $bat
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = "$venvPython,0"
    $shortcut.Description = "ABI Karaoke - make karaoke videos"
    $shortcut.Save()
    Write-Ok "Desktop shortcut created"
}

Write-Step "Verifying"
& $venvPython -m abikaraoke doctor

Write-Host ""
Write-Host "Done. Launch 'ABI Karaoke' from the desktop, or run:" -ForegroundColor Green
Write-Host "    `"$bat`""
Write-Host ""
Write-Host "If vocal removal quality matters, install Demucs (large, ~2.5 GB):" -ForegroundColor Yellow
Write-Host "    `"$venvPython`" -m pip install demucs"

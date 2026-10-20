# Build FreeDM.exe (windowed) and FreeDM-cli.exe (console).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File build.ps1
#   powershell -ExecutionPolicy Bypass -File build.ps1 -SkipCli
#
# The windowed build is the normal application; the console build streams
# live progress in a terminal (the windowed one cannot print anything).

param(
    [switch]$SkipCli,
    [switch]$SkipGui
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "icon.ico")) {
    Write-Host "Generating icon.ico..."
    python scripts\make_icon.py
}

$common = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "FreeDM",
    "--paths", ".",
    "--icon", "icon.ico",
    "--hidden-import", "requests",
    "--collect-submodules", "requests",
    "--add-data", "extension;extension"
)

function Build-App($name, $console) {
    Write-Host ""
    Write-Host "Building $name ..."
    $args = @("-m", "PyInstaller") + $common
    $args = $args -replace "^FreeDM$", $name
    if ($console) {
        $args += "--console"
    } else {
        $args += "--windowed"
    }
    $args += "freedm\main.py"
    & python @args
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed for $name"
    }
}

if (-not $SkipGui) {
    Build-App "FreeDM" $false
}

if (-not $SkipCli) {
    Build-App "FreeDM-cli" $true
}

Write-Host ""
$ok = $true
foreach ($name in @("FreeDM.exe", "FreeDM-cli.exe")) {
    if (Test-Path "dist\$name") {
        $size = [math]::Round((Get-Item "dist\$name").Length / 1MB, 1)
        Write-Host "OK: dist\$name ($size MB)" -ForegroundColor Green
    } elseif ($name -eq "FreeDM.exe" -and $SkipGui) {
        # intentionally not built
    } elseif ($name -eq "FreeDM-cli.exe" -and $SkipCli) {
        # intentionally not built
    } else {
        Write-Host "MISSING: dist\$name" -ForegroundColor Red
        $ok = $false
    }
}

if (-not $ok) {
    exit 1
}

# Build FreeDM.exe (single-file, windowed) with PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Installing/updating PyInstaller..."
python -m pip install --quiet --upgrade pyinstaller

Write-Host "Building FreeDM.exe..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name FreeDM `
    --paths . `
    --hidden-import requests `
    --collect-submodules requests `
    --add-data "extension;extension" `
    freedm\main.py

Write-Host ""
if (Test-Path "dist\FreeDM.exe") {
    $size = [math]::Round((Get-Item "dist\FreeDM.exe").Length / 1MB, 1)
    Write-Host "SUCCESS: dist\FreeDM.exe ($size MB)" -ForegroundColor Green
} else {
    Write-Host "BUILD FAILED: dist\FreeDM.exe not found" -ForegroundColor Red
    exit 1
}

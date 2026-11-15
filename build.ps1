# Builds the portable folder dist\PosterPrint and dist\PosterPrint.zip
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "No .venv found. Create it: py -3.11 -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }

# PyInstaller logs to stderr; under 'Stop' Windows PowerShell 5.1 would treat that as a failure.
$ErrorActionPreference = 'Continue'
& $py -m PyInstaller --noconfirm --clean --windowed --log-level WARN --name PosterPrint `
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtPdf `
    main.py
$ErrorActionPreference = 'Stop'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$zip = Join-Path $PSScriptRoot 'dist\PosterPrint.zip'
if (Test-Path $zip) { Remove-Item $zip -Confirm:$false }
Compress-Archive -Path (Join-Path $PSScriptRoot 'dist\PosterPrint') -DestinationPath $zip
"Built: $zip ({0:N0} MB)" -f ((Get-Item $zip).Length / 1MB)

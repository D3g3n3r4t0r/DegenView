# Build completo: rigenera il sidecar Python (PyInstaller), lo copia nelle
# risorse Tauri, compila l'app desktop, e aggiorna il collegamento sul
# desktop. Un solo comando per testare l'ultima versione dall'app nativa.
#
# Uso:  powershell -ExecutionPolicy Bypass -File build_desktop_app.ps1

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$DesktopApp = Join-Path $Root "desktop-app"
$TauriBinaries = Join-Path $DesktopApp "src-tauri\binaries"

Write-Host "==> Chiudo eventuali processi server sulla porta 8000..." -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Get-Process liquidity-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "==> Build sidecar Python (PyInstaller)..." -ForegroundColor Cyan
Push-Location $Backend
& ".\.venv\Scripts\python.exe" -m PyInstaller liquidity-server.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallito" }
Pop-Location

Write-Host "==> Copio sidecar + .env nelle risorse Tauri..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $TauriBinaries | Out-Null
Copy-Item (Join-Path $Backend "dist\liquidity-server.exe") (Join-Path $TauriBinaries "liquidity-server.exe") -Force
Copy-Item (Join-Path $Backend ".env") (Join-Path $TauriBinaries ".env") -Force

Write-Host "==> Build app Tauri..." -ForegroundColor Cyan
Push-Location (Join-Path $DesktopApp "src-tauri")
cargo tauri build --no-bundle
if ($LASTEXITCODE -ne 0) { throw "Build Tauri fallita" }
Pop-Location

$ExePath = Join-Path $DesktopApp "src-tauri\target\release\liquidity-analysis-engine.exe"
if (-not (Test-Path $ExePath)) { throw "Eseguibile non trovato: $ExePath" }

Write-Host "==> Aggiorno il collegamento sul desktop..." -ForegroundColor Cyan
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopDir "Liquidity Analysis Engine.lnk"
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path $ExePath
$Shortcut.IconLocation = Join-Path $DesktopApp "src-tauri\icons\icon.ico"
$Shortcut.Description = "Liquidity Analysis Engine"
$Shortcut.Save()

Write-Host "==> Fatto. Collegamento aggiornato: $ShortcutPath" -ForegroundColor Green
Write-Host "    Eseguibile: $ExePath" -ForegroundColor Green

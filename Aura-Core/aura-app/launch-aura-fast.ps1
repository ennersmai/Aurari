# ============================================
# AURA AGI - SOVEREIGN NATIVE FAST LAUNCH (PowerShell)
# ============================================
# Skips TTS and prerequisite checks for fastest boot.
# Assumes SurrealDB and Uvicorn are already on PATH.

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    AURA AGI - FAST NATIVE BOOT          " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$auraAppPath = (Get-Location).Path

# 1. SurrealDB
Write-Host "[*] SurrealDB (port 8000)..." -ForegroundColor Cyan
Start-Process pwsh -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'Aura Vector DB'; surreal start --log trace --user root --pass root --bind 127.0.0.1:8000 memory" -WindowStyle Normal
Start-Sleep -Seconds 2

# 2. Uvicorn Backend
Write-Host "[*] Python AI Engine (port 8080)..." -ForegroundColor Cyan

$venvActivate = Join-Path $auraAppPath "venv\Scripts\activate.ps1"
if (Test-Path $venvActivate) {
    $backendCmd = "`$Host.UI.RawUI.WindowTitle = 'Aura Core API'; Set-Location -Path '$auraAppPath'; & '$venvActivate'; uvicorn aura.main:app --host 127.0.0.1 --port 8080 --reload"
} else {
    $backendCmd = "`$Host.UI.RawUI.WindowTitle = 'Aura Core API'; Set-Location -Path '$auraAppPath'; py -m uvicorn aura.main:app --host 127.0.0.1 --port 8080 --reload"
}
Start-Process pwsh -ArgumentList "-NoExit", "-Command", $backendCmd -WindowStyle Normal

# 3. Frontend
if (Test-Path "frontend\package.json") {
    Write-Host "[*] Next.js Frontend (port 3000)..." -ForegroundColor Cyan
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'Aura Frontend'; Set-Location -Path '$auraAppPath\frontend'; npm run dev" -WindowStyle Normal
}

Write-Host ""
Write-Host "[OK] All services launched in visible terminal windows." -ForegroundColor Green
Write-Host "  SurrealDB  →  http://127.0.0.1:8000" -ForegroundColor Gray
Write-Host "  Backend    →  http://127.0.0.1:8080/docs" -ForegroundColor Gray
Write-Host "  Frontend   →  http://localhost:3000" -ForegroundColor Gray
Write-Host ""

# ============================================
# AURA AGI - SOVEREIGN NATIVE LAUNCHER (PowerShell)
# ============================================
# No Docker. No containers. Bare-metal SurrealDB + Uvicorn.
# Each backend service opens in its own visible terminal window
# so you can monitor stdout/stderr in real-time.
#
# PERSISTENT MEMORY: SurrealDB stores all data to disk in .aura/data/
# Aura's memories, skills, relationships, and personality persist across reboots.

# Set encoding to UTF-8 for emoji support
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# ============================================
# CONFIGURATION
# ============================================
# Set this to $true to skip loading heavy local models (TTS/FishAudio) to save RAM and GPU memory.
$LowEndMode = $true

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    AURA AGI - SOVEREIGN NATIVE BOOT     " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# ============================================
# 1. Environment Check
# ============================================
if (-Not (Test-Path ".env")) {
    Write-Host "[!] No .env file found!" -ForegroundColor Yellow
    Write-Host "    Creating .env from env.example..." -ForegroundColor Gray
    
    if (Test-Path "env.example") {
        Copy-Item "env.example" ".env"
        Write-Host "[OK] .env created!" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] env.example missing! Cannot configure." -ForegroundColor Red
        exit 1
    }

    Write-Host ""
    Write-Host "[!] ACTION REQUIRED: Configuration" -ForegroundColor Red
    Write-Host "    Please edit .env and add your keys:" -ForegroundColor White
    Write-Host "    1. OPENROUTER_API_KEY (Required for Brain)" -ForegroundColor Gray
    Write-Host "    2. TAVILY_API_KEY     (Required for Web Search)" -ForegroundColor Gray
    Write-Host ""
    Read-Host "Press Enter after you have saved the .env file..." | Out-Null
}

# ============================================
# 2. Prerequisite Checks
# ============================================
Write-Host ""
Write-Host "[*] Checking prerequisites..." -ForegroundColor Cyan

# Check SurrealDB CLI
$surrealOk = $false
try {
    surreal version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] SurrealDB CLI found." -ForegroundColor Green
        $surrealOk = $true
    }
} catch {}

if (-Not $surrealOk) {
    Write-Host "[ERROR] SurrealDB CLI not found on PATH!" -ForegroundColor Red
    Write-Host "        Install: https://surrealdb.com/install" -ForegroundColor Yellow
    exit 1
}

# Check Python/uvicorn
$uvicornOk = $false
try {
    uvicorn --version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Uvicorn found." -ForegroundColor Green
        $uvicornOk = $true
    }
} catch {}

if (-Not $uvicornOk) {
    Write-Host "[!] Uvicorn not found! Attempting to install dependencies..." -ForegroundColor Yellow
    
    # Try to install from current directory
    if (Test-Path "pyproject.toml") {
        pip install -e .
    } else {
        pip install uvicorn
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies automatically." -ForegroundColor Red
        Write-Host "        Please run setup-env.ps1 manually or install uvicorn." -ForegroundColor Red
        exit 1
    } else {
        Write-Host "[OK] Dependencies installed successfully!" -ForegroundColor Green
    }
}

# ============================================
# 3. Persistent Memory Directory Setup
# ============================================
Write-Host ""
Write-Host "[*] Preparing persistent memory store..." -ForegroundColor Cyan

$auraDataDir = Join-Path (Get-Location) ".aura\data"
$auraDbFile = Join-Path $auraDataDir "aura.db"

# SurrealDB 3.0+ requires a storage protocol prefix (surrealkv:).
# Convert backslashes to forward slashes for SurrealDB compatibility.
$auraDbUri = "surrealkv:" + $auraDbFile.Replace("\", "/")


if (-Not (Test-Path $auraDataDir)) {
    Write-Host "    Creating .aura/data/ directory..." -ForegroundColor Gray
    New-Item -ItemType Directory -Path $auraDataDir -Force | Out-Null
    Write-Host "[OK] Persistent storage directory created." -ForegroundColor Green
} else {
    Write-Host "[OK] Persistent memory store found at $auraDataDir" -ForegroundColor Green
    
    # Report existing data size
    if (Test-Path $auraDbFile) {
        $dbSize = (Get-Item $auraDbFile).Length
        $dbSizeStr = if ($dbSize -gt 1MB) { "{0:N2} MB" -f ($dbSize / 1MB) } elseif ($dbSize -gt 1KB) { "{0:N2} KB" -f ($dbSize / 1KB) } else { "$dbSize B" }
        Write-Host "    Database size: $dbSizeStr" -ForegroundColor DarkGray
    }
}

# ============================================
# 4. Launch SurrealDB with persistent storage (visible terminal window)
# ============================================
Write-Host ""
Write-Host "[*] Launching SurrealDB in visible terminal..." -ForegroundColor Cyan
Write-Host "    Title: Aura Vector DB" -ForegroundColor Gray
Write-Host "    Port:  8000" -ForegroundColor Gray
Write-Host "    Storage: $auraDbUri" -ForegroundColor Gray
Write-Host "    Mode:  persistent (disk-backed)" -ForegroundColor Green

# Launch SurrealDB with persistent file storage.
# Write a temporary script to avoid all pwsh-in-pwsh quoting hell.
# The script contains the literal path, so SurrealDB receives it intact.
$surrealScript = Join-Path $env:TEMP "aura-surreal-launch.ps1"
$scriptContent = @"
`$Host.UI.RawUI.WindowTitle = 'Aura Vector DB'
surreal start --log info --user root --pass root --bind 127.0.0.1:8000 $auraDbUri
"@
Set-Content -Path $surrealScript -Value $scriptContent -Encoding UTF8

Start-Process pwsh -ArgumentList "-NoExit", "-File", $surrealScript -WindowStyle Normal

# Give SurrealDB a moment to bind its port and load data.
Start-Sleep -Seconds 3

# ============================================
# 5. Seed Schema & Initial Data (if empty)
# ============================================
Write-Host ""
Write-Host "[*] Seeding Aura schema into persistent memory..." -ForegroundColor Cyan

$scriptsDir = Join-Path (Get-Location) "scripts"
$seedFiles = @(
    "init_schema.surql",
    "register_local_tools.surql",
    "seed_emotions.surql",
    "seed_cultural_nodes.surql"
)

# Wait for SurrealDB to be ready
$ready = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $testConn = Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
        if ($testConn.TcpTestSucceeded) {
            $ready = $true
            break
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

if ($ready) {
    # SurrealDB 3.0 REST API: use POST /sql with Surreal-NS/Surreal-DB headers.
    $seedHeaders = @{
        "Content-Type"  = "text/plain"
        "Accept"        = "application/json"
        "Authorization" = "Basic cm9vdDpyb290"
        "Surreal-NS"    = "aura"
        "Surreal-DB"    = "aura"
    }
    
    foreach ($seedFile in $seedFiles) {
        $seedPath = Join-Path $scriptsDir $seedFile
        if (Test-Path $seedPath) {
            Write-Host "    Seeding $seedFile..." -ForegroundColor DarkGray
            try {
                $seedBody = Get-Content -Path $seedPath -Raw
                $null = Invoke-RestMethod -Uri "http://127.0.0.1:8000/sql" -Method Post -Headers $seedHeaders -Body $seedBody -ErrorAction Stop
                Write-Host "      [OK] $seedFile seeded." -ForegroundColor Green
            } catch {
                Write-Host "      [!] $($seedFile): ${_}" -ForegroundColor Yellow
            }
        } else {
            Write-Host "      [!] Missing seed file: $seedPath" -ForegroundColor DarkYellow
        }
    }
    
    # Seed initial tasks
    $taskSeed = Join-Path $scriptsDir "setup_tasks.surql"
    if (Test-Path $taskSeed) {
        Write-Host "    Seeding tasks..." -ForegroundColor DarkGray
        try {
            $taskBody = Get-Content -Path $taskSeed -Raw
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:8000/sql" -Method Post -Headers $seedHeaders -Body $taskBody -ErrorAction Stop
            Write-Host "      [OK] setup_tasks.surql seeded." -ForegroundColor Green
        } catch {
            Write-Host "      [!] Tasks seed: ${_}" -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Host "[!] SurrealDB did not become ready in time. Schema seeding skipped." -ForegroundColor Yellow
}

Write-Host "[OK] Aura persistent memory is ready." -ForegroundColor Green

# ============================================
# 6. Launch Python Uvicorn Backend (visible terminal window)
# ============================================
Write-Host ""
Write-Host "[*] Launching Python AI Engine in visible terminal..." -ForegroundColor Cyan
Write-Host "    Title: Aura Core API" -ForegroundColor Gray
Write-Host "    Port:  8080" -ForegroundColor Gray

$auraAppPath = (Get-Location).Path

# Prefer the project venv if it exists; otherwise rely on py launcher.
$venvActivate = Join-Path $auraAppPath "venv\Scripts\activate.ps1"
if (Test-Path $venvActivate) {
    $backendCmd = "`$Host.UI.RawUI.WindowTitle = 'Aura Core API'; Set-Location -Path '$auraAppPath'; & '$venvActivate'; uvicorn aura.main:app --host 127.0.0.1 --port 8080 --reload"
} else {
    $backendCmd = "`$Host.UI.RawUI.WindowTitle = 'Aura Core API'; Set-Location -Path '$auraAppPath'; py -m uvicorn aura.main:app --host 127.0.0.1 --port 8080 --reload"
}
Start-Process pwsh -ArgumentList "-NoExit", "-Command", $backendCmd -WindowStyle Normal

# ============================================
# 7. (Optional) Qwen3-TTS
# ============================================
# Path relative to the repo root (Aura-Core/Qwen3-TTS).
# Adjust $ttsDir if your checkout layout differs.
$ttsDir = Join-Path (Get-Location) "..\Qwen3-TTS"
$ttsPort = 50000

if ($LowEndMode) {
    Write-Host "[*] Low End Mode Active: Skipping Qwen3-TTS local model." -ForegroundColor Yellow
} else {

$ttsAlreadyRunning = $false
try {
    $testConn = Test-NetConnection -ComputerName 127.0.0.1 -Port $ttsPort -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    if ($testConn.TcpTestSucceeded) {
        $ttsAlreadyRunning = $true
    }
} catch {}

if ($ttsAlreadyRunning) {
    Write-Host "[OK] Qwen3-TTS already running on port $ttsPort" -ForegroundColor Green
} elseif (Test-Path $ttsDir) {
    # Priority 1: dedicated TTS venv inside Qwen3-TTS directory.
    $ttsVenvActivate = Join-Path $ttsDir "venv\Scripts\activate.ps1"
    # Priority 2: main aura-app venv (qwen-tts may be installed there via setup-env.ps1).
    $mainVenvActivate = Join-Path $auraAppPath "venv\Scripts\activate.ps1"
    $venvToUse = $null
    $venvLabel = ""

    if (Test-Path $ttsVenvActivate) {
        $venvToUse = $ttsVenvActivate
        $venvLabel = "dedicated TTS venv"
    } elseif (Test-Path $mainVenvActivate) {
        $venvToUse = $mainVenvActivate
        $venvLabel = "main aura-app venv"
    }

    if ($venvToUse) {
        Write-Host "[*] Starting Qwen3-TTS via $venvLabel..." -ForegroundColor Cyan
        Write-Host "    Venv:  $venvToUse" -ForegroundColor DarkGray
        Write-Host "    Port:  $ttsPort" -ForegroundColor DarkGray

        # Refresh PATH from the registry so the TTS subprocess sees any
        # system tools installed earlier in this session (e.g., SoX via winget).
        $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User") + ";" + [Environment]::GetEnvironmentVariable("PATH", "Machine")

        # Resolve the absolute path to the model directory.
        # $ttsDir is already the Qwen3-TTS folder containing config.json & model.safetensors.
        # We must pass an absolute path so transformers never misidentifies it as a Hub repo ID.
        $AbsModelPath = (Resolve-Path $ttsDir).Path

        # Activate the venv, cd into the TTS directory, and launch server.py.
        $ttsCmd = "& '$venvToUse'; Set-Location '$ttsDir'; python server.py --port $ttsPort --model_dir '$AbsModelPath'"
        Start-Process pwsh -ArgumentList "-NoExit", "-Command", $ttsCmd -WindowStyle Normal
        Write-Host "[OK] Qwen3-TTS starting in background window (port $ttsPort)" -ForegroundColor Green
        Start-Sleep -Seconds 2
    } else {
        Write-Host "[!] Qwen3-TTS directory found but no usable venv." -ForegroundColor Yellow
        Write-Host "    Dedicated path: $ttsVenvActivate" -ForegroundColor DarkGray
        Write-Host "    Main app path:  $mainVenvActivate" -ForegroundColor DarkGray
        Write-Host "    Run setup-env.ps1 or create a venv:  cd $ttsDir && python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt" -ForegroundColor DarkGray
        Write-Host "    Edge-TTS (cloud) will be used as fallback." -ForegroundColor DarkGray
    }
} else {
    Write-Host "[!] Qwen3-TTS not found at $ttsDir" -ForegroundColor Yellow
    Write-Host "    Edge-TTS (cloud) will be used as fallback." -ForegroundColor DarkGray
}
}

# ============================================
# 7b. (Optional) FishAudio (GGUF)
# ============================================
# Path relative to the repo root (Aura-Core/FishAudio).
# Drop s2-pro-q4_k_m.gguf (or similar) into this directory.
$fishDir = Join-Path (Get-Location) "..\FishAudio"
$fishPort = 50001

if ($LowEndMode) {
    Write-Host "[*] Low End Mode Active: Skipping FishAudio local model." -ForegroundColor Yellow
} else {

$fishAlreadyRunning = $false
try {
    $testConn = Test-NetConnection -ComputerName 127.0.0.1 -Port $fishPort -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
    if ($testConn.TcpTestSucceeded) {
        $fishAlreadyRunning = $true
    }
} catch {}

if ($fishAlreadyRunning) {
    Write-Host "[OK] FishAudio already running on port $fishPort" -ForegroundColor Green
} elseif (Test-Path $fishDir) {
    # Check for GGUF file
    $ggufFiles = Get-ChildItem -Path $fishDir -Filter "*.gguf" -File
    $ttsVenvActivate = Join-Path $fishDir "venv\Scripts\activate.ps1"
    $mainVenvActivate = Join-Path $auraAppPath "venv\Scripts\activate.ps1"
    $venvToUse = $null
    $venvLabel = ""

    if (Test-Path $ttsVenvActivate) {
        $venvToUse = $ttsVenvActivate
        $venvLabel = "dedicated FishAudio venv"
    } elseif (Test-Path $mainVenvActivate) {
        $venvToUse = $mainVenvActivate
        $venvLabel = "main aura-app venv"
    }

    if ($ggufFiles.Count -gt 0) {
        $ggufName = $ggufFiles[0].Name
        Write-Host "[*] Starting FishAudio GGUF via $venvLabel..." -ForegroundColor Cyan
        Write-Host "    GGUF:  $ggufName" -ForegroundColor DarkGray
        Write-Host "    Port:  $fishPort" -ForegroundColor DarkGray

        # Refresh PATH
        $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User") + ";" + [Environment]::GetEnvironmentVariable("PATH", "Machine")

        $AbsModelPath = (Resolve-Path $fishDir).Path
        $fishCmd = "& '$venvToUse'; Set-Location '$fishDir'; python server.py --port $fishPort --model_dir '$AbsModelPath' --gpu_layers 35"
        Start-Process pwsh -ArgumentList "-NoExit", "-Command", $fishCmd -WindowStyle Normal
        Write-Host "[OK] FishAudio starting in background window (port $fishPort)" -ForegroundColor Green
        Start-Sleep -Seconds 2
    } else {
        Write-Host "[!] FishAudio directory found but no .gguf model file." -ForegroundColor Yellow
        Write-Host "    Drop s2-pro-q4_k_m.gguf (or similar) into: $fishDir" -ForegroundColor DarkGray
        Write-Host "    Download from: https://huggingface.co/fishaudio/fish-speech-1.5" -ForegroundColor DarkGray
        Write-Host "    Edge-TTS (cloud) will be used as fallback." -ForegroundColor DarkGray
    }
} else {
    Write-Host "[!] FishAudio directory not found at $fishDir" -ForegroundColor Yellow
    Write-Host "    Edge-TTS (cloud) will be used as fallback." -ForegroundColor DarkGray
}
}

# ============================================
# 8. Launch Frontend
# ============================================
Write-Host ""
Write-Host "[*] Starting Next.js frontend..." -ForegroundColor Cyan
Write-Host "    Port: 3000" -ForegroundColor Gray

if (Test-Path "frontend\package.json") {
    Start-Process pwsh -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = 'Aura Frontend'; Set-Location -Path '$auraAppPath\frontend'; npm run dev" -WindowStyle Normal
} else {
    Write-Host "[!] frontend/package.json not found. Skipping frontend." -ForegroundColor Yellow
}

# ============================================
# 9. Summary
# ============================================
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "    AURA IS BOOTING (Sovereign Native)    " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  SurrealDB  →  http://127.0.0.1:8000" -ForegroundColor Gray
Write-Host "  Backend    →  http://127.0.0.1:8080/docs" -ForegroundColor Gray
Write-Host "  Frontend   →  http://localhost:3000" -ForegroundColor Gray
if (-not $LowEndMode) {
    if ($ttsAlreadyRunning -or (Test-Path $ttsDir)) {
        Write-Host "  Qwen3-TTS    →  http://127.0.0.1:50000" -ForegroundColor Gray
    }
    if ($fishAlreadyRunning -or ((Test-Path $fishDir) -and ((Get-ChildItem $fishDir -Filter "*.gguf" -File -ErrorAction SilentlyContinue).Count -gt 0))) {
        Write-Host "  FishAudio    →  http://127.0.0.1:50001" -ForegroundColor Gray
    }
} else {
    Write-Host "  Qwen3-TTS    →  [Skipped - Low End Mode]" -ForegroundColor DarkGray
    Write-Host "  FishAudio    →  [Skipped - Low End Mode]" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  Persistent memory: $auraDbFile" -ForegroundColor DarkCyan
Write-Host "  All memories, skills, and relationships survive reboots." -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  Check the terminal windows for real-time logs." -ForegroundColor DarkGray
Write-Host "  Close the terminal windows to stop individual services." -ForegroundColor DarkGray
Write-Host "  To wipe all memory: Remove .aura/ directory and reboot." -ForegroundColor DarkGray
Write-Host ""

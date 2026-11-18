# ============================================================================
# AURA — LEAN VIRTUAL ENVIRONMENT SETUP (PowerShell)
# ============================================================================
# Creates a native Windows Python venv and installs Aura's dependencies,
# including a pre-compiled Qwen3-TTS wheel to bypass all remote C++ compilation.
#
# PERSISTENT MEMORY: Initializes .aura/data/ directory for SurrealDB persistence.
# All of Aura's memories, skills, relationships, and personality are stored here
# and survive reboots, power cycles, and system updates.
#
# NO CONDA. NO COSYVOICE. NO DOCKER.
#
# Usage:
#   .\setup-env.ps1
#
# Prerequisites:
#   - Python 3.12+ on PATH
#   - A pre-compiled Qwen3-TTS .whl file (build from source once, reuse forever)
# ============================================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AURA — Lean Venv Setup                " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ------------------------------------------------------------------
# 1. Verify Python is available
# ------------------------------------------------------------------
Write-Host "[1/5] Checking Python..." -ForegroundColor Cyan

# Resolve a working Python executable.
# On some Windows installs 'python' is hijacked by the Microsoft Store
# App Execution Alias, but 'py' (the Python Launcher) always works.
$pythonExe = $null
foreach ($candidate in @("py", "python", "python3")) {
    try {
        $verCheck = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $candidate
            Write-Host "  Found: $candidate → $verCheck" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonExe) {
    Write-Host "  ERROR: No working Python found (tried py, python, python3)." -ForegroundColor Red
    Write-Host "  Install Python 3.12+ from https://python.org and ensure" -ForegroundColor Red
    Write-Host "  the Python Launcher (py.exe) is on PATH." -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------------
# 2. System Dependencies — SoX (required by qwen-tts for audio processing)
# ------------------------------------------------------------------
Write-Host "[2/7] Checking system dependencies (SoX)..." -ForegroundColor Cyan

$soxOk = $false
try {
    sox --version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  SoX found on PATH." -ForegroundColor Green
        $soxOk = $true
    }
} catch {}

if (-not $soxOk) {
    Write-Host "  SoX not found on PATH." -ForegroundColor Yellow
    Write-Host "  qwen-tts requires sox.exe for audio processing." -ForegroundColor DarkGray

    # Attempt automated install via winget.
    $wingetOk = $false
    try {
        winget --version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $wingetOk = $true
        }
    } catch {}

    if ($wingetOk) {
        Write-Host "  Installing SoX via winget (SourceForge.SoX)..." -ForegroundColor Yellow
        winget install -e --id SourceForge.SoX --silent
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  SoX installed successfully." -ForegroundColor Green
            Write-Host "  NOTE: The current terminal may not see sox yet." -ForegroundColor DarkYellow
            Write-Host "  launch-aura.ps1 refreshes PATH from the registry at boot," -ForegroundColor DarkGray
            Write-Host "  so the TTS server will detect sox.exe automatically." -ForegroundColor DarkGray
        } else {
            Write-Host "  WARNING: winget install returned non-zero exit code." -ForegroundColor Yellow
            Write-Host "  Install SoX manually for qwen-tts support:" -ForegroundColor DarkGray
            Write-Host "    https://sourceforge.net/projects/sox/files/sox/" -ForegroundColor White
            Write-Host "  Edge-TTS (cloud) fallback will be used." -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  WARNING: winget is not available on this system." -ForegroundColor Yellow
        Write-Host "  Install SoX manually for qwen-tts support:" -ForegroundColor DarkGray
        Write-Host "    1. Download: https://sourceforge.net/projects/sox/files/sox/" -ForegroundColor White
        Write-Host "    2. Add sox.exe directory to your system PATH" -ForegroundColor White
        Write-Host "    3. Restart your terminal and re-run this script" -ForegroundColor White
        Write-Host "  Edge-TTS (cloud) will be used as fallback until SoX is installed." -ForegroundColor DarkGray
    }
}

Write-Host ""

# ------------------------------------------------------------------
# 3. Create venv (if missing)
# ------------------------------------------------------------------
Write-Host "[3/7] Setting up virtual environment..." -ForegroundColor Cyan
$venvPath = Join-Path $ScriptDir "venv"
$venvActivate = Join-Path $venvPath "Scripts\activate.ps1"

if (Test-Path $venvActivate) {
    Write-Host "  venv already exists at $venvPath" -ForegroundColor DarkYellow
} else {
    Write-Host "  Creating venv at $venvPath..." -ForegroundColor Yellow
    & $pythonExe -m venv venv
    if (-not (Test-Path $venvActivate)) {
        Write-Host "  ERROR: venv creation failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "  venv created." -ForegroundColor Green
}

# Activate the venv for the remainder of this script.
& $venvActivate

# ------------------------------------------------------------------
# 4. Upgrade pip
# ------------------------------------------------------------------
Write-Host "[4/7] Upgrading pip..." -ForegroundColor Cyan
& $pythonExe -m pip install --upgrade pip --quiet
Write-Host "  pip upgraded." -ForegroundColor Green

# ------------------------------------------------------------------
# 5. Install Qwen3-TTS (PyPI package + flash-attn)
# ------------------------------------------------------------------
Write-Host "[5/7] Installing Qwen3-TTS..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  qwen-tts is the official PyPI package (pure Python, no compilation)." -ForegroundColor DarkGray
Write-Host "  Model weights are already local: ..\Qwen3-TTS\" -ForegroundColor DarkGray
Write-Host ""

# Install the qwen-tts Python package from PyPI
Write-Host "  Installing qwen-tts from PyPI..." -ForegroundColor Yellow
pip install -U qwen-tts
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: qwen-tts installation failed." -ForegroundColor Yellow
    Write-Host "  The TTS server will not start. Edge-TTS (cloud) fallback unaffected." -ForegroundColor DarkGray
} else {
    Write-Host "  qwen-tts installed successfully." -ForegroundColor Green
}

# flash-attn: optional GPU memory optimization (requires C++ compilation)
Write-Host ""
Write-Host "  flash-attn (optional): reduces GPU memory for TTS." -ForegroundColor DarkGray
Write-Host "  NOTE: You previously compiled flash_attn-2.8.3 for Python 3.10 (cp310)." -ForegroundColor DarkYellow
Write-Host "  The venv uses Python 3.12 — that wheel is incompatible." -ForegroundColor DarkYellow
Write-Host "  To compile for Python 3.12:" -ForegroundColor DarkGray
Write-Host "    pip install flash-attn --no-build-isolation" -ForegroundColor White
Write-Host "  This requires MSVC Build Tools + CUDA Toolkit (already installed)." -ForegroundColor DarkGray
Write-Host ""

# Pre-compiled wheel for cp312+cu124+torch2.6.0 (matches this venv exactly).
$flashAttnWhl = Join-Path $ScriptDir "wheels\flash_attn-2.7.4+cu124torch2.6.0cxx11abiFALSE-cp312-cp312-win_amd64.whl"

if (Test-Path $flashAttnWhl) {
    Write-Host "  Found pre-compiled wheel: flash_attn-2.7.4+cu124torch2.6.0-cp312-win_amd64" -ForegroundColor Green

    # Install the complete PyTorch trinity locked to the exact same matrix.
    # This prevents partial upgrades from fracturing DLL entry points
    # across torch, torchvision, and torchaudio.
    Write-Host "  Installing PyTorch 2.6.0+cu124 trinity (torch + torchvision + torchaudio)..." -ForegroundColor Yellow
    pip install torch==2.6.0+cu124 torchvision==0.21.0+cu124 torchaudio==2.6.0+cu124 `
        --index-url https://download.pytorch.org/whl/cu124 --force-reinstall
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: PyTorch trinity install failed." -ForegroundColor Yellow
    }

    Write-Host "  Installing flash_attn from wheel..." -ForegroundColor Yellow
    pip install $flashAttnWhl
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: flash-attn wheel install failed." -ForegroundColor Yellow
        Write-Host "  TTS server works without it (just uses more GPU memory)." -ForegroundColor DarkGray
    } else {
        Write-Host "  flash-attn 2.7.4 installed successfully." -ForegroundColor Green
    }
} else {
    Write-Host "  No pre-compiled flash-attn wheel found." -ForegroundColor DarkGray
    Write-Host "  TTS uses standard attention (higher VRAM)." -ForegroundColor DarkGray
    Write-Host "  To compile from source: pip install flash-attn --no-build-isolation" -ForegroundColor DarkGray
    Write-Host "  (Requires VS 2022 Build Tools — VS 2025 MSVC is incompatible.)" -ForegroundColor DarkGray
}

# ------------------------------------------------------------------
# 6. Install SGLang inference server (optional, for local LLM RP)
# ------------------------------------------------------------------
Write-Host "[6/7] Installing SGLang inference server..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  SGLang provides RadixAttention for long-context RP within 24 GB VRAM." -ForegroundColor DarkYellow
Write-Host "  NOTE: On native Windows, CUDA Toolkit 12.x and MSVC Build Tools are" -ForegroundColor DarkYellow
Write-Host "  required for FlashInfer JIT compilation.  If these are not installed," -ForegroundColor DarkYellow
Write-Host "  the pip install may fail — the launcher will still work without SGLang." -ForegroundColor DarkYellow
Write-Host ""

$installSglang = Read-Host "Install SGLang? [y/N] (default: N)"

if ($installSglang -eq "y" -or $installSglang -eq "Y") {
    Write-Host "  Installing sglang (uvloop is Linux-only, skipped automatically)..." -ForegroundColor Yellow
    # Install WITHOUT [all] extra — uvloop lives in [all] and is Linux-only.
    # Core sglang + runtime deps work fine on Windows with Developer Mode.
    pip install sglang
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: SGLang installation failed." -ForegroundColor Yellow
        Write-Host "  SGLang is optional — Aura uses cloud LLMs without it." -ForegroundColor DarkGray
    } else {
        Write-Host "  SGLang installed successfully." -ForegroundColor Green
    }
} else {
    Write-Host "  Skipping SGLang installation." -ForegroundColor DarkGray
}

# ------------------------------------------------------------------
# 7. Install Discord Bot dependency (optional)
# ------------------------------------------------------------------
Write-Host "[7/8] Installing Discord Bot support..." -ForegroundColor Cyan
Write-Host ""
Write-Host "  discord.py allows Aura to connect as a Discord bot." -ForegroundColor DarkGray
Write-Host "  This is OPTIONAL — Aura works fine without it." -ForegroundColor DarkGray
Write-Host ""

$installDiscord = Read-Host "Install discord.py (Discord Bot support)? [Y/n] (default: Y)"

if ($installDiscord -eq "" -or $installDiscord -eq "y" -or $installDiscord -eq "Y") {
    Write-Host "  Installing discord.py>=2.3.0..." -ForegroundColor Yellow
    pip install "discord.py>=2.3.0"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: discord.py installation failed." -ForegroundColor Yellow
        Write-Host "  You can install it later: pip install discord.py>=2.3.0" -ForegroundColor DarkGray
    } else {
        Write-Host "  discord.py installed successfully." -ForegroundColor Green
        Write-Host ""
        Write-Host "  To connect Aura to Discord:" -ForegroundColor Cyan
        Write-Host "    1. Go to https://discord.com/developers/applications" -ForegroundColor White
        Write-Host "    2. Click 'New Application' → name it 'Aura'" -ForegroundColor White
        Write-Host "    3. Go to 'Bot' tab → 'Add Bot'" -ForegroundColor White
        Write-Host "    4. Under 'Privileged Gateway Intents', enable:" -ForegroundColor White
        Write-Host "       ✓ MESSAGE CONTENT INTENT (required!)" -ForegroundColor DarkYellow
        Write-Host "    5. Click 'Reset Token' → copy the token" -ForegroundColor White
        Write-Host "    6. Paste it into .env: AURA_DISCORD_BOT_TOKEN=<token>" -ForegroundColor White
        Write-Host "    7. Go to OAuth2 → URL Generator, select 'bot' scope" -ForegroundColor White
        Write-Host "    8. Select permissions: Send Messages, Read Messages, Read Message History" -ForegroundColor White
        Write-Host "    9. Open the generated URL to invite the bot to your server" -ForegroundColor White
        Write-Host "    10. Set AURA_DISCORD_ENABLED=true in .env" -ForegroundColor White
        Write-Host ""
    }
} else {
    Write-Host "  Skipping Discord Bot support." -ForegroundColor DarkGray
}

# ------------------------------------------------------------------
# 8. Install remaining Python requirements
# ------------------------------------------------------------------
Write-Host "[8/8] Installing remaining Python dependencies..." -ForegroundColor Cyan

$requirementsPath = Join-Path $ScriptDir "requirements.txt"
if (Test-Path $requirementsPath) {
    pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: Some dependencies may have failed to install." -ForegroundColor Yellow
    } else {
        Write-Host "  All requirements installed." -ForegroundColor Green
    }
} else {
    # Fallback: install the package in editable mode from pyproject.toml
    Write-Host "  No requirements.txt found — installing via pyproject.toml..." -ForegroundColor DarkYellow
    Set-Location $ScriptDir
    & $pythonExe -m pip install -e .
    Set-Location $ScriptDir
    Write-Host "  Package installed in editable mode." -ForegroundColor Green
}

# ------------------------------------------------------------------
# 9. Persistent Memory Storage Initialization
# ------------------------------------------------------------------
Write-Host ""
Write-Host "[9/9] Initializing persistent memory storage..." -ForegroundColor Cyan

$auraDataDir = Join-Path $ScriptDir ".aura\data"
$auraDbFile = Join-Path $auraDataDir "aura.db"

if (Test-Path $auraDbFile) {
    $dbSize = (Get-Item $auraDbFile).Length
    $dbSizeStr = if ($dbSize -gt 1MB) { "{0:N2} MB" -f ($dbSize / 1MB) } elseif ($dbSize -gt 1KB) { "{0:N2} KB" -f ($dbSize / 1KB) } else { "$dbSize B" }
    Write-Host "  Existing persistent memory found: $dbSizeStr" -ForegroundColor Green
    Write-Host "  Aura will retain all memories across reboots." -ForegroundColor DarkGreen
} else {
    Write-Host "  Creating persistent memory store at $auraDataDir..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $auraDataDir -Force | Out-Null
    
    # Create an empty SurrealDB file (SurrealDB will auto-initialize on first write)
    # We create a marker file so we know this is Aura's data directory
    $markerContent = @"
# Aura Persistent Memory Store
# ============================
# This directory stores Aura's long-term memory in SurrealDB format.
#
# What persists here:
#   - Memories (ingested facts, experiences, relationships)
#   - Skills & tools registered with the system
#   - Emotional state vectors
#   - Cultural context nodes
#   - Task history and progress
#
# To wipe all memory:
#   Remove this entire .aura/ directory, then reboot Aura.
#
# Backup recommendation:
#   Periodically copy aura.db to preserve your AI's memories.
"@
    Set-Content -Path (Join-Path $auraDataDir "README.md") -Value $markerContent -Encoding UTF8
    Write-Host "  [OK] Persistent memory store created." -ForegroundColor Green
    Write-Host "  Aura's memories will begin accumulating on first boot." -ForegroundColor DarkGreen
}

# ------------------------------------------------------------------
# Done
# ------------------------------------------------------------------
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  AURA VENV SETUP COMPLETE              " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Persistent memory: $auraDbFile" -ForegroundColor DarkCyan
Write-Host "  All memories survive reboots automatically." -ForegroundColor DarkCyan
Write-Host ""
Write-Host "  To activate the venv manually:" -ForegroundColor Cyan
Write-Host "    .\venv\Scripts\activate.ps1" -ForegroundColor White
Write-Host ""
Write-Host "  To start Aura:" -ForegroundColor Cyan
Write-Host "    .\launch-aura.ps1" -ForegroundColor White
Write-Host ""
Write-Host "  To wipe all memory (dangerous):" -ForegroundColor Yellow
Write-Host "    Remove-Item -Recurse -Force .aura\" -ForegroundColor DarkRed
Write-Host ""
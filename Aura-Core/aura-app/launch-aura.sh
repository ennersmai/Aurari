#!/usr/bin/env bash
# ============================================
# AURA AGI - SOVEREIGN NATIVE LAUNCHER (Bash)
# ============================================
# No Docker. No containers. Bare-metal SurrealDB + Uvicorn.
# Each backend service opens in its own terminal window.

set -euo pipefail

echo "=========================================="
echo "    AURA AGI - SOVEREIGN NATIVE BOOT     "
echo "=========================================="
echo ""

# 1. Environment Check
if [ ! -f ".env" ]; then
    echo "[!] No .env file found!"
    if [ -f "env.example" ]; then
        cp env.example .env
        echo "[OK] .env created from env.example"
    else
        echo "[ERROR] env.example missing! Cannot configure."
        exit 1
    fi
    echo ""
    echo "[!] ACTION REQUIRED: Edit .env and add your API keys"
    echo "    Press Enter after editing..."
    read -r
fi

# 2. Prerequisites
echo ""
echo "[*] Checking prerequisites..."

if command -v surreal &> /dev/null; then
    echo "[OK] SurrealDB CLI found."
else
    echo "[ERROR] SurrealDB CLI not found! Install: https://surrealdb.com/install"
    exit 1
fi

if command -v uvicorn &> /dev/null; then
    echo "[OK] Uvicorn found."
else
    echo "[ERROR] Uvicorn not found! Install: pip install uvicorn"
    exit 1
fi

# 3. Launch SurrealDB
echo ""
echo "[*] Launching SurrealDB..."
surreal start --log trace --user root --pass root --bind 127.0.0.1:8000 memory &
SURREAL_PID=$!
sleep 2

# 4. Launch Uvicorn Backend
echo "[*] Launching Python AI Engine..."
AURA_APP_PATH="$(pwd)"
uvicorn aura.main:app --host 127.0.0.1 --port 8080 --reload &
UVICORN_PID=$!

# 5. Launch Frontend
if [ -f "frontend/package.json" ]; then
    echo "[*] Starting Next.js frontend..."
    cd frontend && npm run dev &
    FRONTEND_PID=$!
    cd ..
fi

echo ""
echo "=========================================="
echo "    AURA IS BOOTING (Sovereign Native)    "
echo "=========================================="
echo ""
echo "  SurrealDB  →  http://127.0.0.1:8000  (PID: $SURREAL_PID)"
echo "  Backend    →  http://127.0.0.1:8080/docs  (PID: $UVICORN_PID)"
echo "  Frontend   →  http://localhost:3000"
echo ""

# Trap Ctrl+C to clean up child processes
cleanup() {
    echo ""
    echo "[*] Shutting down Aura services..."
    kill $SURREAL_PID 2>/dev/null || true
    kill $UVICORN_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    wait
    echo "[OK] All services stopped."
}
trap cleanup EXIT INT TERM

# Wait for any child to exit
wait

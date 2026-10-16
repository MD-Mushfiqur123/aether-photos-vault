#!/usr/bin/env bash
# ==============================================================================
# AETHER PHOTOS // LINUX & MACOS LAUNCHER
# Author: Md Mushfiqur Rahim & L
# ==============================================================================

set -e

echo ""
echo "==========================================================================="
echo "  AETHER PHOTOS // INFINITE YOUTUBE OBJECT VAULT"
echo "==========================================================================="

if command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
else
    echo "❌ Error: Python 3 is required but not installed."
    exit 1
fi

echo "[*] Found Python ($PY_CMD)"

(
    sleep 1.5
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://localhost:8000" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "http://localhost:8000" >/dev/null 2>&1 || true
    fi
) &

echo "==========================================================================="
echo "🚀 STARTING AETHER PHOTOS STUDIO AT http://localhost:8000"
echo "==========================================================================="
exec $PY_CMD server.py

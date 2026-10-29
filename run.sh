#!/usr/bin/env bash
set -e

echo "========================================"
echo "  ClipClean — Video Processing Tool"
echo "========================================"
echo

# ── Check Python ──────────────────────────────────────────
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "[ERROR] Python 3 is not installed."
    echo "  Install it with your package manager, e.g.:"
    echo "    Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
    echo "    macOS (Homebrew):  brew install python"
    exit 1
fi
echo "[OK] Python found: $($PYTHON --version)"

# ── Check FFmpeg ──────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
    echo "[OK] FFmpeg found."
else
    echo "[WARNING] FFmpeg is NOT found."
    echo "  Install it:"
    echo "    Ubuntu/Debian:  sudo apt install ffmpeg"
    echo "    macOS (Homebrew):  brew install ffmpeg"
    echo "    Fedora:  sudo dnf install ffmpeg"
    echo
    echo "  The app will start but cannot process videos without FFmpeg."
    echo
fi

# ── Virtual environment ──────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv .venv
fi

source .venv/bin/activate
echo "[OK] Virtual environment activated."

# ── Install dependencies ──────────────────────────────────
echo "Installing dependencies..."
pip install -r requirements.txt -q
echo "[OK] Dependencies installed."

# ── Start ─────────────────────────────────────────────────
echo
echo "========================================"
echo "  Starting ClipClean server..."
echo "========================================"
echo
echo "  Open your browser and go to:"
echo
echo "    http://127.0.0.1:8000"
echo
echo "  Press Ctrl+C to stop."
echo "========================================"
echo

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

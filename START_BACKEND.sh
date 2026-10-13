#!/usr/bin/env bash
# ParkSense macOS / Linux Backend Server Launcher

cd "$(dirname "$0")"

echo "========================================================="
echo "           PARKSENSE FLASK BACKEND SERVER"
echo "========================================================="
echo ""
echo "Starting Flask application on http://127.0.0.1:5000..."
echo "Serving API and Frontend simultaneously."
echo ""

if [ -f ".venv/bin/python" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    PYTHON_EXEC="venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_EXEC="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_EXEC="python"
else
    echo "[ERROR] No Python interpreter found. Please install Python 3.9+."
    exit 1
fi

"$PYTHON_EXEC" backend.py


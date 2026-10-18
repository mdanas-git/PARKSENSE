#!/usr/bin/env bash
# ParkSense macOS / Linux Wokwi Cloudflare Tunnel Launcher

cd "$(dirname "$0")"

echo "========================================================="
echo "      PARKSENSE WOKWI CLOUDFLARE INTEGRATION TUNNEL"
echo "========================================================="
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

if [ -f "tools/tunnel_runner.py" ]; then
    "$PYTHON_EXEC" tools/tunnel_runner.py
elif [ -f "tunnel_runner.py" ]; then
    "$PYTHON_EXEC" tunnel_runner.py
else
    echo "Python runner failed, starting cloudflared directly..."
    if [ -f "./cloudflared" ]; then
        if file "./cloudflared" | grep -q "gzip"; then
            echo "[INFO] Detected compressed cloudflared archive. Extracting..."
            mv ./cloudflared ./cloudflared.tgz && tar -xzf ./cloudflared.tgz && rm -f ./cloudflared.tgz
        fi
        chmod +x ./cloudflared
        ./cloudflared tunnel --url http://127.0.0.1:5000
    elif command -v cloudflared >/dev/null 2>&1; then
        cloudflared tunnel --url http://127.0.0.1:5000
    else
        echo "[ERROR] 'cloudflared' binary not found."
        echo "Download it into this directory or install via: brew install cloudflared"
        exit 1
    fi
fi


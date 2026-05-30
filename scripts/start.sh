#!/usr/bin/env bash
# scripts/start.sh — Start the evo_prompt backend server
# Usage: bash scripts/start.sh [--port 8000] [--host 127.0.0.1] [--no-reload]

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$PROJECT_ROOT/.venv/bin/python"
HOST="127.0.0.1"
PORT="8000"
RELOAD="--reload"

# Parse optional flags
while [[ $# -gt 0 ]]; do
    case $1 in
        --host)    HOST="$2";  shift 2 ;;
        --port)    PORT="$2";  shift 2 ;;
        --no-reload) RELOAD=""; shift ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# Check venv exists
if [[ ! -f "$VENV" ]]; then
    echo "[!] Virtual environment not found at $PROJECT_ROOT/.venv"
    echo "    Run: uv venv && uv pip install -r requirements.txt"
    exit 1
fi

# Check MongoDB is reachable
if ! mongosh --quiet --eval "db.runCommand({ ping: 1 })" > /dev/null 2>&1; then
    echo "[!] MongoDB does not appear to be running on localhost:27017"
    echo "    Start it with: sudo systemctl start mongod"
    exit 1
fi

echo "[+] MongoDB is reachable"
echo "[+] Starting evo_prompt on http://$HOST:$PORT"
echo ""

cd "$PROJECT_ROOT"
exec "$VENV" -m uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    $RELOAD

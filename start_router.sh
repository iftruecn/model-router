#!/bin/bash
# Model Router 启动脚本 (Linux/Mac)
# Usage: ./start_router.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting Model Router..."
echo "Endpoint: http://127.0.0.1:6060"
echo "API Docs: http://127.0.0.1:6060/docs"

python3 -m uvicorn model_router.app:app --host 127.0.0.1 --port 6060

#!/usr/bin/env bash
# Aditya-L1 Flare Operations — one-command demo launcher (macOS / Linux)
#
#   bash scripts/start.sh
#
# Ensures pipeline outputs exist, builds the React frontend if needed, then
# serves the full app (API + WebSocket + dashboard) from a single port.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f "outputs/pipeline_summary.txt" ]; then
  echo "==> No pipeline outputs found. Running synthetic showcase pipeline..."
  python -m pipeline.run_pipeline --source synthetic
fi

if [ ! -f "frontend/dist/index.html" ]; then
  echo "==> Building frontend..."
  cd "$ROOT/frontend"
  [ -d node_modules ] || npm install
  npm run build
  cd "$ROOT"
fi

echo "==> Starting Aditya-L1 Flare Operations Center at http://127.0.0.1:8000"
exec uvicorn backend.app:app --host 127.0.0.1 --port 8000

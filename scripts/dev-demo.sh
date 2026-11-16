#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
runtime_dir="$repo_dir/storage/demo"
if ! node -e 'const [major,minor]=process.versions.node.split(".").map(Number);if(major<22||(major===22&&minor<13))process.exit(1)'; then
  echo "Use Node 22.13 or later (cd frontend && nvm use)." >&2
  exit 1
fi
for executable in ffmpeg ffprobe; do command -v "$executable" >/dev/null || { echo "Install $executable first." >&2; exit 1; }; done
[ -x "$repo_dir/backend/.venv/bin/uvicorn" ] || { echo "Install backend dependencies first; see README." >&2; exit 1; }
[ -f "$repo_dir/frontend/node_modules/next/dist/bin/next" ] || { echo "Run npm ci in frontend first." >&2; exit 1; }
mkdir -p "$runtime_dir/logs"
export DATABASE_URL="sqlite:///$runtime_dir/jobs.db"
export LOCAL_STORAGE_PATH="$runtime_dir/media"
export GENERATION_MODE=demo
export CELERY_BROKER_URL=filesystem://
demo_api_port="${DEMO_API_PORT:-8000}"
demo_ui_port="${DEMO_UI_PORT:-3000}"
export FRONTEND_ORIGIN="http://localhost:$demo_ui_port"
export NEXT_PUBLIC_API_URL="http://localhost:$demo_api_port"
export NEXT_TELEMETRY_DISABLED=1
cd "$repo_dir/backend"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$demo_api_port" >"$runtime_dir/logs/api.log" 2>&1 &
api_pid=$!
.venv/bin/celery -A app.workers.celery_app:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO --without-gossip --without-mingle --without-heartbeat >"$runtime_dir/logs/worker.log" 2>&1 &
worker_pid=$!
(cd "$repo_dir/frontend" && exec node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port "$demo_ui_port") >"$runtime_dir/logs/frontend.log" 2>&1 &
ui_pid=$!
cleanup() { kill "$api_pid" "$worker_pid" "$ui_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM
echo "Demo mode: http://localhost:$demo_ui_port — real rendering; deterministic copy, no AI analysis."
echo "Logs: $runtime_dir/logs. Ctrl-C stops these processes."
while true; do
  for service_pid in "$api_pid" "$worker_pid" "$ui_pid"; do
    if ! kill -0 "$service_pid" 2>/dev/null; then
      echo "A service stopped. Inspect the logs above." >&2
      exit 1
    fi
  done
  sleep 2
done

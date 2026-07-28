#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run: bash scripts/bootstrap_local.sh" >&2
  exit 1
fi
source .venv/bin/activate

uvicorn thiezer.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT

cd apps/mobile
flutter run -d macos --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000

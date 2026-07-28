#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv. Run: bash scripts/bootstrap_local.sh" >&2
  exit 1
fi
source .venv/bin/activate

DEVICE_ID="$(
  flutter devices --machine | python3 -c '
import json
import sys

devices = json.load(sys.stdin)
print(next((str(device["id"]) for device in devices if str(device.get("targetPlatform", "")).startswith("ios")), ""))
'
)"
if [[ -z "$DEVICE_ID" ]]; then
  echo "No booted iOS Simulator was found. Open Simulator and retry." >&2
  exit 1
fi

uvicorn thiezer.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT

cd apps/mobile
flutter run -d "$DEVICE_ID" --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000

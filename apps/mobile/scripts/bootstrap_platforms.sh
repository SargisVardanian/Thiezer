#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v flutter >/dev/null 2>&1; then
  echo "Flutter is not installed or not on PATH."
  echo "Install Flutter, then run this script again."
  exit 1
fi

flutter create \
  --platforms=ios,macos \
  --org com.thiezer \
  --project-name thiezer_app \
  .

python3 scripts/patch_apple_permissions.py
flutter pub get

echo
echo "Apple platform hosts are ready."
echo "macOS: flutter run -d macos --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000"
echo "iOS Simulator: flutter run -d ios --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000"
echo "Physical iPhone: use your Mac LAN IP and run uvicorn with --host 0.0.0.0"

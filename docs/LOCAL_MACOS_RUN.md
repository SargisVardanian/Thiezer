# Local macOS run

The default development configuration uses no PostgreSQL or Docker:

```bash
THIEZER_STORAGE_MODE=ephemeral THIEZER_DATABASE_ENABLED=false \
  uvicorn thiezer.main:app --host 127.0.0.1 --port 8000
cd apps/mobile
flutter pub get
flutter run -d macos --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000
```

On this project, Flutter host projects are intentionally generated locally with
`./scripts/bootstrap_platforms.sh` and are ignored by Git. Do not commit `ios/`, `macos/`,
`build/`, `.dart_tool/`, or personal Xcode settings.

If a shell has stale Homebrew compiler variables, run the build with Xcode's compiler explicitly:

```bash
CC=/usr/bin/clang CXX=/usr/bin/clang++ flutter run -d macos
```

The backend can be checked first at `/health/ready`, then catalogue search can be exercised with
`Sirius`, `M31`, `Jupiter`, and an exoplanet such as `51 Peg b`. Exoplanet previews intentionally
describe host-star visibility only.

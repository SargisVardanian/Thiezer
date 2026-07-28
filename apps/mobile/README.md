# Thiezer Flutter client

One Flutter UI targets iOS and macOS.

## Bootstrap Apple platform hosts

The repository stores the reviewed Dart application and generates standard Flutter/Xcode host files
locally so they stay aligned with the Flutter version installed on your Mac.

```bash
cd apps/mobile
chmod +x scripts/bootstrap_platforms.sh
./scripts/bootstrap_platforms.sh
```

## Run backend

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn thiezer.main:app --reload --host 0.0.0.0
```

## Run macOS

```bash
cd apps/mobile
flutter run -d macos \
  --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000
```

## Run iOS Simulator

```bash
flutter run -d ios \
  --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000
```

## Run a physical iPhone

Use the Mac's LAN address because `127.0.0.1` on the phone is the phone itself:

```bash
flutter run -d <DEVICE_ID> \
  --dart-define=THIEZER_API_BASE_URL=http://192.168.1.20:8000
```

The UI also lets you change the API URL at runtime.

## Catalog targets

The discovery screen retains Moon, Mars, Jupiter, Milky Way and best-night-sky presets. The catalog
field debounces requests for 450 ms and ignores stale responses, then shows provider attribution on
each result. Selecting an exoplanet requests host-star visibility; it does not claim that the planet
is directly visible.

## Validate

```bash
flutter pub get
flutter analyze
flutter test
```

The map uses the public OpenStreetMap tile endpoint only for local development. Before public
distribution, configure a production tile provider or self-hosted PMTiles service.

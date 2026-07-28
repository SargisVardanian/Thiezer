# Thiezer

**Find the sky worth traveling for.**

Thiezer is a global, radius-based astronomy travel application. It combines offline JPL
ephemerides, hourly weather, dynamically discovered observation candidates, explainable Sky Score,
equipment-store discovery, a Flutter client, and zero-key route handoffs.

## Spatial model

The default search radius is 250 km.

- Large countries are naturally divided into local searches around the user.
- Small countries can include nearby countries without special-case code.
- `scope=country` is available when a strict national boundary is required.
- `scope=adaptive` is the default and is border-agnostic inside the radius.

Armenia remains a packaged validation dataset because it is convenient for field testing; it is not
the product boundary.

## Implemented

- Alpha Centauri, Mars, Jupiter, Moon, Milky Way core, and general night sky.
- Offline Skyfield/JPL DE421 geometry.
- Batched Open-Meteo weather.
- Global OSM/Overpass discovery for observatories, viewpoints, campsites, parking, and candidate
  equipment stores.
- Explainable Sky Score v1.
- Google Maps, Apple Maps, Yandex web, and `geo:` route handoffs.
- Flutter UI for iOS and macOS.
- Ruff, Mypy, Pytest, Flutter analyze, and Flutter test CI.

## Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn thiezer.main:app --reload --host 0.0.0.0
```

Swagger: `http://127.0.0.1:8000/docs`

## Apple client

```bash
cd apps/mobile
chmod +x scripts/bootstrap_platforms.sh
./scripts/bootstrap_platforms.sh
flutter run -d macos \
  --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000
```

See:

- `docs/GLOBAL_DISCOVERY.md`
- `docs/ARMENIA_MVP.md`
- `apps/mobile/README.md`

All packaged and dynamically discovered observation points remain unverified until field or partner
validation confirms legal access, parking, roads, and nighttime safety.

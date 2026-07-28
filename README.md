# Thiezer

**Find the sky worth traveling for.**

Thiezer is a global, radius-first astronomy travel application. It combines surface-first site
discovery, static geospatial layers, hourly weather, offline ephemerides, explainable sky quality,
equipment-store discovery, and zero-key navigator handoffs.

## What works now

- Targets: Alpha Centauri, Mars, Jupiter, Moon, Milky Way core, and general dark sky.
- `adaptive`, strict `country`, and border-agnostic `global` search scopes.
- Default 250 km hard radius; large countries are searched locally, small countries may cross borders.
- H3 coarse-to-fine surface search before OSM access-point lookup.
- Optional local VIIRS/DEM/land-cover surface packs with conservative global fallback.
- Open-Meteo elevation and chunked hourly weather requests.
- Offline Skyfield/JPL DE421 astronomy calculations.
- Separate `SkyQuality` and `TravelUtility` calculations.
- Google Maps, Apple Maps, Yandex web, and `geo:` route handoffs.
- Flutter client for iOS and macOS.

All dynamically discovered locations are unverified until legal access, road condition, parking and
nighttime safety are checked.

## Repository map

- `services/api` — FastAPI modular backend and scientific/domain code.
- `apps/mobile` — shared Flutter client for iOS and macOS.
- `docs/GLOBAL_DISCOVERY.md` — discovery pipeline, budgets and limitations.
- `docs/SURFACE_PACK.md` — optional static surface-pack contract.
- `scripts` — local bootstrap and Apple demo commands.

## Run locally on macOS

```bash
./scripts/bootstrap_local.sh
./scripts/run_macos_demo.sh
```

The API is available at `http://127.0.0.1:8000/docs`.

## Run in the iOS Simulator

```bash
./scripts/bootstrap_local.sh
./scripts/run_ios_simulator_demo.sh
```

For a physical iPhone, run the API with `--host 0.0.0.0` and enter
`http://<your-mac-lan-ip>:8000` in the app settings. Local HTTP is development-only; production
builds must use HTTPS.

## Backend validation

```bash
source .venv/bin/activate
ruff check .
ruff format --check .
mypy services/api/src
pytest -q
```

## Flutter validation

```bash
cd apps/mobile
flutter analyze
flutter test
```

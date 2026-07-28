# Thiezer

**Find the sky worth traveling for.**

Thiezer is a surface-first astronomy travel prototype. It searches physical terrain before asking
where an observation point has already been mapped.

## Search pipeline

```text
radius and boundary policy
→ H3 coarse coverage
→ DEM / land cover / night-light static scoring
→ coarse-to-fine refinement
→ spatial diversity
→ representative accessible point inside each final cell
→ weather
→ astronomy
→ route handoff and travel utility
```

This avoids the POI-first failure mode in which an unmarked dark plateau can never become a
candidate.

## Implemented

- Targets: Alpha Centauri, Mars, Jupiter, Moon, Milky Way core, and general night sky.
- `adaptive`, strict `country`, and border-agnostic `global` search scopes.
- H3 resolution 5→7 refinement for searches up to 300 km.
- Surface features: elevation, slope, roughness, water, urban, forest, openness, multiscale light
  pressure, access potential, restrictions, uncertainty, static score and upper bound.
- Optional real COG mode for Copernicus DEM, ESA WorldCover and VIIRS/Black Marble.
- Deterministic zero-key procedural mode for CI and disconnected development; it is explicitly
  marked as a proxy and must not be presented as calibrated real-world darkness.
- Local-only Overpass access discovery around shortlisted cells; no radius-wide POI scan.
- Open-Meteo automatic chunking above 25 points with bounded concurrency and per-point elevation.
- Application-scoped HTTP clients and providers.
- Offline Skyfield/JPL DE421 geometry.
- Google Maps, Apple Maps, Yandex web and `geo:` route handoffs.
- Equipment-store search and Flutter UI for iOS and macOS.

`adaptive` and `global` are radius-first and border-agnostic. The bundled strict-country polygon is
currently limited to Armenia (`AM`); production country mode requires a global administrative
boundary dataset.

All generated and OSM-discovered sites remain unverified until legal access, roads, parking,
private-land constraints and nighttime safety are confirmed.

## Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
uvicorn thiezer.main:app --reload --host 0.0.0.0
```

Swagger: `http://127.0.0.1:8000/docs`

## Real geodata mode

Install the optional stack and provide COG assets:

```bash
pip install -e '.[dev,geodata]'
export THIEZER_SURFACE_PROVIDER=cog
export THIEZER_DEM_COG_URL=/data/copernicus-dem.tif
export THIEZER_WORLDCOVER_COG_URL=/data/worldcover.tif
export THIEZER_VIIRS_COG_URL=/data/viirs-night-lights.tif
```

Production refuses to start with the procedural fixture. Use:

```bash
export THIEZER_ENVIRONMENT=production
export THIEZER_SURFACE_PROVIDER=cog
```

Without a VIIRS asset, darkness is marked as a proxy. See `docs/SURFACE_SEARCH.md`.

To build the Armenia + 300 km field package from official source assets, see
[`docs/LOCAL_REAL_DATA_SETUP.md`](docs/LOCAL_REAL_DATA_SETUP.md). Rasters stay local; the tracked
manifest records source attribution, checksums and processed metadata.

## Apple client

```bash
cd apps/mobile
chmod +x scripts/bootstrap_platforms.sh
./scripts/bootstrap_platforms.sh
flutter run -d macos \
  --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000
```

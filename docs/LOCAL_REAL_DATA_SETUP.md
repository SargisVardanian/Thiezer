# Local real-data setup (macOS)

## Prerequisites

Python 3.12+, GDAL/rasterio, Flutter, Xcode and CocoaPods are required for the full macOS run.
Docker Desktop is required only for the local PostgreSQL/PostGIS container. Allocate at least 15 GB
free for an Armenia + 300 km raw/staging/processed run; exact sizes are recorded after download.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,geodata]'
make geodata-armenia
```

The download is resumable: valid files are retained, each completed source asset gets a SHA-256,
and temporary files are atomically renamed. Outputs are `data/processed/armenia_300km` and are
intentionally ignored by Git.

## Production COG run

```bash
cat > .env.local <<'EOF'
THIEZER_ENVIRONMENT=production
THIEZER_SURFACE_PROVIDER=cog
THIEZER_DEM_COG_URL=data/processed/armenia_300km/copernicus_dem.tif
THIEZER_WORLDCOVER_COG_URL=data/processed/armenia_300km/worldcover.tif
THIEZER_VIIRS_COG_URL=
EOF
set -a; source .env.local; set +a
.venv/bin/uvicorn thiezer.main:app --app-dir services/api/src --host 127.0.0.1 --port 8000
```

VNP46A4 access requires NASA Earthdata credentials. Set `THIEZER_EARTHDATA_TOKEN` only in a local
environment file; do not commit it. An absent VIIRS COG is a blocked/calibration limitation, not a
synthetic replacement.

## Validate and run clients

```bash
make backend-check
cd apps/mobile
./scripts/bootstrap_platforms.sh
flutter pub get
flutter analyze
flutter test
flutter run -d macos --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000
```

For iOS Simulator: `flutter config --enable-ios`, open Simulator, then run `flutter run -d ios`.
Delete local data with `rm -rf data/raw/armenia_300km data/staging/armenia_300km data/processed/armenia_300km`; manifests remain available for audit. To update a release, re-run download/build/validate with a new AOI or source version and review the resulting manifest diff.

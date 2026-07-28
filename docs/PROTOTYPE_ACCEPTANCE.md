# Prototype acceptance

Run from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy services/api/src
pytest -q
```

Run Flutter validation:

```bash
cd apps/mobile
flutter pub get
flutter analyze
flutter test
```

Surface-search acceptance is encoded in tests:

- exhaustive H3 resolution-7 oracle inside 250 km of Yerevan;
- Top-10 recall at least 95%;
- best-score regret at most 0.02;
- zero radius-wide Overpass calls;
- no more than 40 weather candidates;
- 40 weather coordinates require exactly two Open-Meteo batches;
- travel distance never changes darkness;
- spatial NMS removes near-duplicate results.

The procedural provider validates algorithms and control flow without network cost. It is not a
claim of real-world terrain or darkness accuracy. For field use, install the geodata extra and
configure DEM, WorldCover and VIIRS COG assets.

# Armenia-first discovery MVP

This slice answers three practical questions:

1. Is a selected object geometrically observable from the user's location and time?
2. Which nearby candidate site in Armenia has the best weather-adjusted observation window?
3. Where can the user find astronomy equipment and how can they hand the destination to a navigator?

## Supported targets

- Alpha Centauri
- Mars
- Jupiter
- Moon
- Milky Way core, represented operationally by the Galactic centre direction
- General dark night sky

Alpha Centauri is intentionally included as a negative scientific test. Its declination is about
-60.8 degrees, so from Armenia's roughly 38-41 degree north latitude it never rises above the
geometric horizon. Armenia-scoped searches should therefore return no invented recommendation and
include `target_not_visible_in_scope`.

## Runtime data flow

```text
user coordinates + target + UTC range
    -> country-scoped seed-site shortlist
    -> one batched Open-Meteo request for the shortlist
    -> offline JPL DE421 target/Sun/Moon geometry for every site-hour
    -> normalized quality components
    -> hard gates
    -> weighted geometric Sky Score v1
    -> distance/risk/confidence utility
    -> ranked observation windows + route handoffs
```

The current seed list contains candidate areas, not validated parking points. Every observation site
is marked `unverified_seed`; the API must expose that warning. Before public release, legal access,
road status, parking, seasonal closure, mobile coverage, and nighttime safety need field verification.

## Scientific calculations

### Equatorial to horizontal coordinates

For observer latitude `phi`, object declination `delta`, and hour angle `H`:

```text
sin(h) = sin(phi) sin(delta) + cos(phi) cos(delta) cos(H)
```

Production object, Sun, and Moon coordinates are calculated with Skyfield using the packaged JPL
DE421 ephemeris. This avoids runtime ephemeris downloads.

### Air mass

Kasten-Young:

```text
X = 1 / (cos(z) + 0.50572 * (96.07995 - z)^(-1.6364))
```

where `z = 90 degrees - altitude`.

### Cloud clearance

A low-cost layer-aware transmission proxy is used:

```text
layer = exp(-(2.8 low + 2.0 mid + 1.4 high))
cloud_clearance = 0.65 layer + 0.35 (1 - total_cloud)
```

The coefficients are versioned operational parameters, not universal physical constants.

### Transparency proxy

```text
transparency = 0.50 visibility + 0.30 humidity_term + 0.20 air_mass_term
```

This is deliberately labelled a proxy until CAMS aerosol optical depth and local validation are
added.

### Moon interference

Moon interference depends on illumination, altitude, angular separation from the target, and target
sensitivity. If the Moon is below the horizon, its interference score is 1.0. Milky Way and general
dark-sky searches are more sensitive than planet searches.

### Dew, wind, altitude, and horizon

- Dew uses the observed temperature minus provider dew point.
- Wind is stricter for wide-angle camera mode.
- Site altitude uses a saturating benefit rather than unlimited reward.
- Horizon openness is currently a site-level seed feature; directional DEM-derived horizon profiles
  are a later data-ingestion task.

### Score and utility

Hard gates invalidate a sample for insufficient darkness, target below the operational horizon,
severe cloud, measurable precipitation, or inaccessible place.

Valid samples use a target-specific weighted geometric mean:

```text
Q = product(component_i ^ weight_i)
```

The ranking utility is:

```text
U = Q - 0.20 drive_cost - 0.15 place_risk - 0.15 (1 - forecast_confidence)
```

A geometric mean prevents an excellent darkness value from numerically compensating for a nearly
zero critical component.

## API

### List targets

```bash
curl http://localhost:8000/v1/targets
```

### Check target geometry

```bash
curl 'http://localhost:8000/v1/targets/jupiter/visibility?latitude_deg=40.1772&longitude_deg=44.5035&at_utc=2026-07-29T20:00:00Z'
```

### Find the best Armenia sites

```bash
curl -X POST http://localhost:8000/v1/recommendations/search \
  -H 'content-type: application/json' \
  -d '{
    "user_location": {"latitude_deg": 40.1772, "longitude_deg": 44.5035},
    "target": "milky_way",
    "observation_mode": "naked_eye",
    "start_utc": "2026-07-29T18:00:00Z",
    "end_utc": "2026-08-03T02:00:00Z",
    "scope": "country",
    "country_code": "AM",
    "max_distance_km": 300,
    "max_results": 5
  }'
```

`scope=global` is already represented in contracts, but current packaged coverage is Armenia only.
The response reports `coverage_country_codes` so clients do not confuse an empty data region with an
astronomical no-result.

### Find equipment stores

```bash
curl -X POST http://localhost:8000/v1/stores/search \
  -H 'content-type: application/json' \
  -d '{
    "user_location": {"latitude_deg": 40.1772, "longitude_deg": 44.5035},
    "scope": "country",
    "country_code": "AM",
    "max_distance_km": 300
  }'
```

Physical results contain Google Maps, Apple Maps, Yandex web, and `geo:` route handoffs. Online-only
stores expose their official catalog without pretending to have a physical route.

## Navigation policy

- Google Maps URLs are the default zero-key directions handoff.
- Apple Maps links are included for Apple devices.
- Yandex web links are best-effort only. The documented native Yandex app scheme needs an issued
  access key before coordinates can be passed reliably.
- `geo:` is the local-device fallback on platforms that support it.

Thiezer currently ranks by straight-line distance to avoid paid routing calls. Actual travel time is
displayed by the selected external navigator. A later two-stage optimization can request road times
only for the top three to five candidates.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn thiezer.main:app --reload
```

Validation:

```bash
ruff check .
ruff format --check .
mypy services/api/src
pytest -q
```

No live network calls are made by the test suite.

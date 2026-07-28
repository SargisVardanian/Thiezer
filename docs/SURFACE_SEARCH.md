# Surface-first search

## Objective separation

Thiezer keeps three concepts separate:

- `SurfaceSuitability`: physical quality of the terrain;
- `SkyQuality`: astronomical and atmospheric quality at a time;
- `TravelUtility`: quality after distance, risk and uncertainty penalties.

Travel distance is never an input to darkness.

## Static score

Each surface cell contains elevation, slope, roughness, multiscale light radiance, water, urban,
forest and open-land fractions, road and settlement distance, restriction flags and uncertainty.

Multiscale light pressure:

```text
L = 0.55 log(1 + R0-5) + 0.30 log(1 + R5-25) + 0.15 log(1 + R25-80)
darkness = exp(-L / scale)
```

Surface components are combined with a weighted geometric mean so a nearly unusable component
cannot be hidden by an unrelated strong component.

Hard filters reject restricted cells, excessive water or urban coverage, steep terrain, poor access
potential and excessive uncertainty.

## H3 refinement

For a 250 km query:

1. cover the search circle at H3 resolution 5;
2. evaluate static layers for all coarse cells;
3. select spatially diverse parents by static upper bound;
4. expand only those parents to resolution 7;
5. evaluate and filter fine cells;
6. keep a spatially diverse fine shortlist;
7. choose a real representative point inside each cell;
8. query local OSM access only around the strongest cells;
9. send no more than 40 candidates to weather evaluation.

Country scope additionally filters cell centers against a boundary polygon. Adaptive and global
scope remain radius-bounded and may cross borders.

## Data modes

### Procedural

The default development provider is deterministic and costs nothing. It validates control flow,
budgets, invariants and oracle metrics, but its surface values are proxies.

### COG

The production-oriented provider reads small windows from explicit local or remote Cloud Optimized
GeoTIFF assets:

- Copernicus DEM;
- ESA WorldCover;
- VIIRS/Black Marble night lights.

If VIIRS is omitted, the API reports proxy darkness. The COG provider transforms WGS84 points into
the raster CRS, derives DEM slope and roughness, and calculates WorldCover fractions.

## Access discovery

OSM is not the surface generator. Overpass runs only inside 2–10 km around at most 16 shortlisted
surface cells. It materializes parking, viewpoints, campsites and nearby road access. Failures fall
back to in-cell surface sampling.

Public Overpass remains a prototype fallback. Production should use cached regional PBF/PostGIS
access data.

## Weather

Open-Meteo requests are automatically chunked at 25 coordinates, limited to three concurrent
batches, and include per-point elevation. A 40-candidate search therefore uses at most two weather
requests.

## Validation

The CI suite compares the production coarse-to-fine search against an exhaustive H3 resolution-7
oracle within 250 km of Yerevan.

Required checks:

- Top-10 recall at least 95%;
- best-score regret at most 0.02;
- zero radius-wide Overpass calls;
- no more than 40 weather candidates;
- automatic weather chunking above 25 points;
- no near-duplicate final sites;
- travel distance cannot change darkness.

The oracle validates the search algorithm against the deterministic fixture. Field accuracy still
requires real raster assets and verified access observations.

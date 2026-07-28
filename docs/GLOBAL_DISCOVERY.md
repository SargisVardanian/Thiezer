# Global radius-first discovery

Administrative borders are not the primary search geometry. Every search has a hard radius, 250 km
by default:

- large countries remain local because only cells inside the radius are evaluated;
- small countries may include neighbouring countries in `adaptive` or `global` mode;
- `country` applies an optional strict country filter while preserving the radius bound.

## Surface-first pipeline

```text
user point + radius
  -> H3 coarse coverage
  -> static surface layers and hard filters
  -> diverse coarse parent shortlist
  -> H3 refinement
  -> static shortlist and spatial NMS
  -> local OSM access materialisation around final cells
  -> chunked weather
  -> astronomy
  -> SkyQuality
  -> TravelUtility
  -> navigator handoff
```

OSM points are not used to decide where good sky exists. They are queried only near shortlisted
surfaces to find a practical parking, viewpoint, campsite or road-access point.

## Default budgets

For approximately 250 km:

- H3 resolution 5 coarse scan;
- up to 24 spatially diverse parents;
- refinement to H3 resolution 7;
- up to 60 static cells;
- local access lookup for at most 40 cells, each within 1-10 km;
- weather in chunks of 25 with concurrency 2;
- at most 10 returned routes, all as external zero-key URLs.

Larger radii automatically use coarser starting resolutions to keep computational cost bounded.

## Static layers

`SurfaceCell` supports:

- VIIRS/Black Marble radiance;
- DEM elevation;
- slope and roughness;
- water, urban, forest and restricted fractions;
- road and settlement distance;
- horizon openness;
- static score, optimistic upper bound and uncertainty.

A configured local surface pack is preferred. Global elevation can be retrieved from Open-Meteo.
When VIIRS, land cover or restrictions are unavailable, Thiezer uses a conservative fallback and
returns `static_layers_fallback`; it does not claim calibrated sky brightness.

## Hard filters

A surface is rejected before weather calls when it exceeds configured limits for water, urban land,
slope or restricted area, or when its static score is too low.

## SkyQuality versus TravelUtility

Sky quality contains only observation conditions: darkness, clouds, transparency, Moon, target
altitude, terrain, dew, wind, accessibility and forecast confidence.

Travel utility is calculated afterwards from:

```text
sky quality
- radius-normalised travel penalty
- place risk
- static-data uncertainty
- forecast uncertainty
- verification penalty
```

This prevents proximity to the user from changing the physical darkness estimate.

## Country filtering

The default `adaptive` mode does not require country resolution. Strict `country` mode uses an
offline nearest-settlement resolver and is therefore marked approximate near borders. A production
deployment can replace it with exact country polygons without changing recommendation contracts.

## Production data path

Public Overpass and public raster tiles are development fallbacks. A scaled deployment should use:

- regional OSM PBF imported into PostGIS;
- local H3-keyed static surface packs;
- cached weather grid cells;
- validated access and restriction records;
- HTTPS API deployment and private map-tile service.

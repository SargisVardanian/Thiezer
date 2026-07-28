# Static surface-pack format

Set `THIEZER_SURFACE_PACK_PATH` to a UTF-8 JSON file. The root may be a list or an object with a
`cells` list. Each row is keyed by an H3 cell.

```json
{
  "cells": [
    {
      "h3_index": "872b5a375ffffff",
      "country_code": "AM",
      "elevation_m": 2200.0,
      "slope_deg": 4.5,
      "roughness_score": 0.12,
      "viirs_radiance_nw_cm2_sr": 0.18,
      "darkness_score": 0.91,
      "water_fraction": 0.0,
      "urban_fraction": 0.02,
      "forest_fraction": 0.10,
      "restricted_fraction": 0.0,
      "distance_to_road_km": 1.7,
      "distance_to_settlement_km": 22.0,
      "horizon_openness_score": 0.88,
      "uncertainty": 0.12,
      "source": "viirs-dem-landcover-2026-07"
    }
  ]
}
```

`static_score` and `upper_bound` may be supplied, but the runtime recomputes them when omitted.
Recommended preprocessing sources are VIIRS/Black Marble, Copernicus DEM, land cover, protected and
restricted polygons, and OSM road distance. Preserve source dates, licences and attribution outside
the numerical pack.

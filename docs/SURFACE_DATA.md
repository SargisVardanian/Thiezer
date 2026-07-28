# Surface data contract

The COG provider consumes explicit local paths or URLs for one DEM, one ESA WorldCover raster, and
optionally one VIIRS night-light raster. It never discovers data at request time.

`scripts/geodata` builds the pack outside Git. It supports an AOI defined as a geodesic center and
radius, bbox, GeoJSON `Polygon`, or `MultiPolygon`; no script assumes Armenia beyond the selected
configuration file.

## Sources

- Copernicus DEM GLO-90 through the public Microsoft Planetary Computer STAC API. This is a DSM;
  use the official Copernicus terms and required attribution.
- ESA WorldCover 2021 v200 through Planetary Computer STAC. Licence: CC BY 4.0; attribution:
  `© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data 2021 processed by ESA WorldCover consortium`.
- NASA Black Marble VNP46A4 for calibrated nighttime radiance. Its Earthdata-access requirement is
  explicit. Until a verified asset is supplied, production may run with DEM/WorldCover but reports
  darkness as a proxy and must not claim calibrated darkness.

The per-AOI manifest contains the exact STAC item IDs, immutable source URLs without expiring query
parameters, SHA-256 values, output CRS/resolution/bounds, and preprocessing metadata.

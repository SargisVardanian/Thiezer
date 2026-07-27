# Data sources

All providers must be used through adapters and reviewed for attribution, rate limits, caching, redistribution, and commercial-use terms before production.

## Planned sources

- Weather: Open-Meteo during prototype; commercial endpoint before paid launch.
- Ephemerides: local deterministic calculations; JPL Horizons for validation and uncommon objects.
- Atmospheric composition: CAMS for aerosols, smoke, dust, and water-vapour signals.
- Ground air observations: OpenAQ v3 where station licensing permits.
- Night lights: VIIRS products with required attribution.
- Terrain: Copernicus DEM or another explicitly licensed DEM.
- Roads and places: OpenStreetMap-derived data, self-hosted tiles, Wikidata, manual validation.
- Navigation: external Google Maps, Apple Maps, or Yandex URL handoff first.

## Data rules

1. Preserve provider name, model/run time, requested coordinate, returned grid coordinate, and attribution.
2. Never treat AQI as astronomical transparency.
3. Never present long-range aurora probability as a local sighting promise.
4. Do not use public OpenStreetMap tile servers as production infrastructure.

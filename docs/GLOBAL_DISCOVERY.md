# Global adaptive discovery

Thiezer uses a radius as the primary spatial constraint. Country size does not determine the
workload:

- in a large country, a 250 km search evaluates only the user's surrounding region;
- in a small country, `scope=adaptive` or `scope=global` may cross borders;
- `scope=country` is an explicit strict filter and still remains radius-bounded.

## Default request

```json
{
  "user_location": {"latitude_deg": 40.1772, "longitude_deg": 44.5035},
  "target": "milky_way",
  "observation_mode": "naked_eye",
  "start_utc": "2026-07-28T18:00:00Z",
  "end_utc": "2026-08-04T02:00:00Z",
  "scope": "adaptive",
  "country_code": null,
  "max_distance_km": 250,
  "max_candidates": 16,
  "max_results": 5
}
```

`global` does not mean scanning every point on Earth. It means "do not apply a national boundary
inside the requested radius."

## Candidate discovery

The runtime repository merges:

1. packaged or partner-verified places;
2. OpenStreetMap features discovered through Overpass:
   - observatories;
   - viewpoints;
   - campsites;
   - non-private parking areas.

Results are deduplicated and ranked cheaply before weather is requested.

## Cost control

```text
user position
  -> radius-bounded OSM discovery
  -> static shortlist
  -> one batched Open-Meteo call
  -> local Skyfield/JPL geometry
  -> Sky Score
  -> external navigator URLs
```

No paid map, places, astronomy, or routing API is required for the development slice.

## Darkness limitations

Dynamic global discovery currently uses `settlement_distance_proxy_v1`, based on mapped nearby
cities/towns/villages, population when available, distance from the user, and place type.

It is not a calibrated sky-brightness measurement. Every such result returns
`darkness_is_proxy`. The production replacement is a tiled VIIRS/Black Marble radiance layer plus
atmospheric scattering and user/SQM calibration.

## Safety

OSM-discovered results are `unverified_discovered`. The application must show that legal access,
private land, final road condition, weather hazards, parking, and nighttime safety are not guaranteed.

## Flutter client

`apps/mobile` contains one Flutter UI for iOS and macOS. It provides:

- current or manually entered coordinates;
- target selection;
- 25-500 km radius;
- adaptive, country-only, and cross-border modes;
- recommendation cards and OSM development map;
- external Google Maps, Apple Maps, Yandex, and `geo:` route handoffs;
- nearby equipment-store discovery;
- editable backend URL.

See `apps/mobile/README.md`.

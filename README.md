# Thiezer

**Find the sky worth traveling for.**

Thiezer is an astronomy travel recommendation engine. The Armenia-first API combines
astronomical geometry, hourly weather, seed observation sites, explainable Sky Score v1,
equipment-store discovery, and route handoffs.

## Implemented vertical slice

- Targets: Alpha Centauri, Mars, Jupiter, Moon, Milky Way core, and general night sky.
- Country-scoped recommendation search, currently backed by Armenia seed data.
- Offline JPL DE421 ephemerides through Skyfield and packaged `skyfield-data`.
- Batched Open-Meteo weather requests for candidate sites.
- Explainable task-specific scoring with hard visibility and safety gates.
- Equipment stores in Armenia.
- Google Maps, Apple Maps, Yandex web, and local `geo:` route handoffs.

All seed observation locations are marked `unverified_seed`. They are candidate areas, not
claims of legal access or nighttime safety.

See [`docs/ARMENIA_MVP.md`](docs/ARMENIA_MVP.md) for API examples, formulas, limitations, and
local commands.

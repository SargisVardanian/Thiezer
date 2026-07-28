# Celestial data providers

Thiezer resolves celestial targets on demand; it does not maintain a persistent star or place catalog.

| Provider | Purpose | Cache | Attribution |
| --- | --- | --- | --- |
| SIMBAD TAP | Names, aliases, classes, ICRS coordinates | 24 h | SIMBAD, CDS, Strasbourg |
| Gaia DR3 TAP | Astrometry, proper motion, photometry | 7 d | ESA/Gaia/DPAC |
| VizieR TAP | Allowlisted specialist/deep-sky catalogs | 24 h | CDS/VizieR |
| NED TAP/API | Extragalactic metadata | 24 h | NASA/IPAC Extragalactic Database |
| NASA Exoplanet Archive TAP | Confirmed planets and host metadata | 24 h | NASA Exoplanet Archive |
| JPL Horizons | Comets, asteroids, satellites, spacecraft | 30 min | JPL Horizons |
| Skyfield DE421 | Sun, Moon and major-planet presets | local | JPL DE421 via Skyfield |

Every adapter uses typed input, strict result caps, bounded retries, timeout and attribution. User table,
column and ADQL fragments are never accepted. Catalog metadata cache keys never include observer
coordinates, signed URLs or tokens. An exoplanet result always reports host-star visibility; it never
claims direct visual detection of the planet.

Local development uses deterministic fixtures where a provider is unavailable. Live catalog checks are
opt-in only and must produce redacted reports.

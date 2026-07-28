# Query-driven architecture

Default runtime is ephemeral: no PostgreSQL, Docker, local raster pack, persistent catalog or query
history is required. A request resolves its celestial target, generates H3 candidates, reads bounded
surface data, fetches weather, calculates astronomy, checks access for finalists, ranks results, and
returns an expiring result. Exact observer coordinates are used only in-flight and are never cache keys
or persisted records.

`THIEZER_STORAGE_MODE=ephemeral` and `THIEZER_DATABASE_ENABLED=false` are the supported local default.

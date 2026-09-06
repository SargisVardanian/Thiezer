# Thiezer agent guide

## Mission
Build an astronomy travel product that returns reproducible, explainable recommendations. Never fabricate forecast or astronomy values.

## Repository map
- `services/api/src/thiezer/domain`: provider-independent models and deterministic calculations.
- `services/api/src/thiezer/providers`: external integrations hidden behind interfaces.
- `services/api/src/thiezer/api`: HTTP transport only; no scientific logic in routers.
- `services/api/src/thiezer/persistence`: database infrastructure.
- `services/api/tests`: unit, property, adapter, and API tests.
- `docs`: product and architecture decisions.

## Commands
```bash
pip install -e '.[dev]'
make lint
make typecheck
make test
make run
```

## Rules
1. Keep a modular monolith. Do not add service-to-service HTTP calls.
2. Domain calculations must be deterministic, unit-explicit, documented, and tested against independent references.
3. External providers require interfaces, timeouts, bounded retries, attribution metadata, and recorded fixtures.
4. Store timezone-aware UTC internally.
5. Scores use `[0, 1]` internally; presentation may expose `[0, 100]`.
6. Coefficients belong in versioned configuration, not unexplained constants inside code paths.
7. Never commit secrets, tokens, `.env`, or live provider responses containing restricted data.
8. Do not add AI, social, billing, or booking before the recommendation vertical slice works.
9. Keep celestial catalog lookup query-driven and ephemeral. Preserve string presets, use typed identifiers and fixed provider query templates, and never describe an exoplanet as directly visible.

## Product-v1 implementation contract (2026-09-06)
Read `docs/PRODUCT_V1_IMPLEMENTATION.md` before changing discovery, Map/Sky, routing or commercial features.

The owner has a newer local planetarium than the inspected remote branch. Inspect local status/diff/untracked work first. Do not reset, clean, force-push or replace that workspace with this older remote baseline. Preserve the actual current renderer and astronomy implementation.

Implement complete vertical slices, not only plans, TODOs or static mockups. Use a feature flag for the first integration of `domain/opportunity_policy.py`. Its tests prove policy behavior only; it does not fetch providers, create sites, calculate ephemerides or route roads, and is not integrated into the API by this change.

Default discovery is country-first and time-budget-aware. Verify candidate, snapped endpoints and full route geometry. Environmental light sources across borders still matter. Compute each observing interval for its own site. Never silently relax Sun/Moon, travel or country constraints to make results appear.

Unknown is not zero, safe, clear or accessible. Keep forecast-backed, partial forecast, astronomy-only and unverified access distinct. A forecast-backed result is not a guarantee of weather or safety. Never label an uncalibrated score as a success probability.

The UI and new identifiers stay English. Keep geolocation, manual planning location and map camera separate. Preserve source-backed catalogue stars; a decorative sky is not a scientific planetarium. Show true route geometry or explicitly unavailable routing. General dark sky has no single target altitude/azimuth.

Use the connected tools where applicable, but do not claim macOS launch, visual QA or 60 FPS without direct evidence. Report implemented, integrated, tested and proposed separately. Do not buy services, activate billing or publish a release without owner approval.

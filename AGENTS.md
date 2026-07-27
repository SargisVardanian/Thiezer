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

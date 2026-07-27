# Initial architecture

```text
Flutter / Web
      ↓
FastAPI modular monolith
      ↓
Sky · Astronomy · Places · Media · Recommendations
      ↓
PostgreSQL + PostGIS · object storage · background worker
```

## Decisions

- One deployable API and one worker at the beginning.
- Modules may become services later, but communicate in-process now.
- PostgreSQL/PostGIS is canonical storage.
- Provider adapters are replaceable and never leak provider-specific structures into domain contracts.
- Redis, Kubernetes, embedded navigation, and event buses are not initial dependencies.

## First data flow

Providers → normalized hourly conditions → deterministic astronomy geometry → task-specific Sky Score → ranked places → route handoff and explanation.

## Reliability boundaries

- Network calls live only in provider adapters.
- Tests never depend on live provider endpoints.
- All timestamps are timezone-aware UTC.
- Scientific calculations expose tolerances and use independent reference fixtures.
- AI may later call backend tools, but cannot mutate forecasts or manufacture values.

# Next Codex task: recommendation contracts and Armenia fixtures

Work only inside this repository. Read `AGENTS.md`, `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/SCORING_V0.md`, and the existing tests before changing code.

## Goal

Implement the provider-independent contracts and service skeleton required for the first recommendation endpoint without introducing live network calls, paid routing, authentication, AI, social features, or separate microservices.

## Deliverables

1. Add domain contracts for:
   - `CandidatePlace`;
   - `PlaceAccess`;
   - `ObservationWindow`;
   - `RankedPlace`;
   - `RecommendationSearchRequest`;
   - `RecommendationSearchResponse`;
   - `ExplanationItem`;
   - `RouteHandoff`.
2. Add a `PlaceRepository` protocol and an in-memory repository used only by tests and local demo mode.
3. Add a `RecommendationService` that:
   - filters candidates by straight-line distance;
   - evaluates provided hourly normalized conditions;
   - rejects hard-gated windows;
   - calculates Sky Score v0;
   - applies distance, risk, and confidence utility penalties;
   - returns deterministic top results.
4. Add `POST /v1/recommendations/search` with dependency injection.
5. Add 5–10 clearly labelled synthetic Armenia fixtures. Do not claim that synthetic fixtures are validated observation sites.
6. Add unit, API, deterministic snapshot, and N+1 query-count tests.
7. Update documentation only where implementation decisions require it.

## Constraints

- All timestamps are timezone-aware UTC.
- All units are explicit in field names or typed value objects.
- Domain contracts contain no provider-specific fields.
- No router contains scoring or ranking logic.
- No live API call is allowed in tests.
- Do not add Redis, Celery, Kubernetes, billing, maps SDKs, or an LLM.
- Do not silently change Sky Score coefficients.

## Required validation

```bash
ruff check .
ruff format --check .
mypy services/api/src
pytest -q
```

## Completion report

At the end, provide:

- changed files;
- contract decisions;
- API example request and response;
- tests executed and exact results;
- unresolved scientific or product assumptions;
- no commit unless explicitly requested.

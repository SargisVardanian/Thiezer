# Thiezer

**Find the sky worth traveling for.**

Thiezer is an astronomy travel platform that turns a visual goal into an actionable observation plan:

`photo or target → nearby ranked places → best time window → honest conditions → route handoff`

This repository contains the first engineering foundation for the astronomy product. The previous unrelated newsroom implementation is preserved in the Git branch `archive/newsroom-before-astronomy`.

## Current scope

- Modular FastAPI backend
- Provider-independent domain contracts
- Deterministic astronomy calculations
- Explainable task-specific Sky Score v0
- Open-Meteo provider adapter
- PostgreSQL/PostGIS development stack
- Alembic migration foundation
- Unit, property, adapter, and API tests
- GitHub Actions CI

The first supported observation targets are the Milky Way, Moon, and bright planets. Observation modes are naked eye, binoculars, and wide-angle camera.

## Repository map

- `services/api` — FastAPI modular monolith and domain packages
- `docs` — product, architecture, scoring, data-source, and roadmap decisions
- `.github/workflows` — automated linting, type checking, and tests
- `docker-compose.yml` — local PostGIS and API environment

## Local setup

Python 3.12 is the reference runtime.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
cp .env.example .env
make test
make run
```

API documentation is available at `http://localhost:8000/docs`.

## Docker setup

```bash
docker compose up --build
```

## Validation

```bash
make lint
make typecheck
make test
```

## First vertical slice

Visual home → “Find this sky” → nearby ranked locations → hourly conditions → route handoff → save location.

Community media, observatory booking, stores, subscriptions, embedded navigation, and AI are intentionally deferred until the recommendation loop is accurate and useful.

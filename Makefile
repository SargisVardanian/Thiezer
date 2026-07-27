.PHONY: install run lint format typecheck test migrate

install:
	python -m pip install -e '.[dev]'

run:
	uvicorn thiezer.main:app --app-dir services/api/src --reload

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy services/api/src

test:
	pytest -q

migrate:
	alembic -c services/api/alembic.ini upgrade head

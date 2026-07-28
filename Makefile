.PHONY: install run lint format typecheck test migrate geodata-armenia-download geodata-armenia-build geodata-armenia-validate geodata-armenia backend-check flutter-check demo-macos

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

geodata-armenia-download:
	.venv/bin/python scripts/geodata/download_surface_data.py --aoi configs/aoi/armenia_300km.json

geodata-armenia-build:
	.venv/bin/python scripts/geodata/build_surface_cogs.py --aoi configs/aoi/armenia_300km.json

geodata-armenia-validate:
	.venv/bin/python scripts/geodata/validate_surface_cogs.py --aoi configs/aoi/armenia_300km.json

geodata-armenia: geodata-armenia-download geodata-armenia-build geodata-armenia-validate

backend-check:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/mypy services/api/src
	.venv/bin/pytest -q

flutter-check:
	cd apps/mobile && flutter pub get && flutter analyze && flutter test

demo-macos:
	cd apps/mobile && flutter run -d macos --dart-define=THIEZER_API_BASE_URL=http://127.0.0.1:8000

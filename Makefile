.PHONY: check test run up down

# One command that has to pass before every PR.
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy --strict src
	uv run pytest -q

test:
	uv run pytest -q

run:
	uv run python -m src.server

# --wait holds until the healthchecks pass, so Odoo is really ready afterwards.
up:
	docker compose up -d --wait db odoo

down:
	docker compose down

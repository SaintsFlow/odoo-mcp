.PHONY: check test run up down seed demo

# Where the stand lives when it runs on this machine. Override any of these in
# the environment to point the commands somewhere else.
ODOO_URL ?= http://localhost:8069
ODOO_DB ?= odoo
ODOO_USER ?= admin
ODOO_PASSWORD ?= admin

STAND = ODOO_URL=$(ODOO_URL) ODOO_DB=$(ODOO_DB) ODOO_USER=$(ODOO_USER) ODOO_PASSWORD=$(ODOO_PASSWORD)

# One command that has to pass before every PR. The coverage threshold sits in
# pyproject.toml, so this line and CI cannot disagree about it.
check:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy --strict src
	uv run pytest -q --cov=src

test:
	uv run pytest -q

run:
	uv run python -m src.server

# --wait holds until the healthchecks pass, so Odoo is really ready afterwards.
up:
	docker compose up -d --wait db odoo

down:
	docker compose down

# Predictable data on top of the demo: one customer, one product, a known
# quantity of it. Running it twice changes nothing.
seed:
	$(STAND) uv run python -m src.seed

# The whole path an agent walks, against the running stand. Needs make seed first.
demo:
	$(STAND) uv run python -m src.demo

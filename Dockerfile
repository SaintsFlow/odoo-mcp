# Build stage installs the dependencies, the runtime image only carries the result.
FROM python:3.12-slim AS build

# uv is pinned on purpose: a floating tag would change the resolver under us.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies change much less often than the code, so they get their own layer.
# README.md comes along because pyproject points at it and the wheel build reads it.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

# The server has no reason to run as root.
RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app
CMD ["python", "-m", "src.server"]

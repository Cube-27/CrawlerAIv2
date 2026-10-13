# The single backend image (SPEC-00 §2). Build from the repo root: docker build -f infra/Dockerfile backend
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
WORKDIR /app

# Dependencies install from wheels only, so no third-party build script runs.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-build --no-install-project

# The project alone is built from this repo's source and installed non-editable; dependencies stay wheel-only.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-build --no-binary-package crawlerai --no-editable
COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --system --no-create-home crawlerai
USER crawlerai

EXPOSE 8000
CMD ["uvicorn", "--factory", "crawlerai.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

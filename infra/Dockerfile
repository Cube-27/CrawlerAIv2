# The single backend image (SPEC-00 §2). Build from the repo root, naming the commit for the engine version:
#   docker build -f infra/Dockerfile --build-arg CRAWLERAI_GIT_SHA=$(git rev-parse HEAD) backend
# The build stage installs the project into a virtual environment; the image keeps that environment and the
# migrations only, so the engine's data is held once, inside the installed package.
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies install from wheels only, so no third-party build script runs.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra parquet --no-build --no-install-project

# The fetched data files are downloaded and checked against their pinned sha256 before the project is built, since the
# build hook puts the manifest's data files in the wheel (hatch_build.py). `crawlerai data fetch` without the CLI, which
# needs the installed project: `core/data.py` imports the standard library only, so copied alone this layer re-runs
# only when the data or the fetch changes, not on every `src/` change. A refused entry is printed and left out of the
# image, which then reports it missing at run time.
COPY data ./data
COPY src/crawlerai/core/data.py ./fetch_data.py
RUN python -c "from pathlib import Path; from fetch_data import fetch_data; \
    print(*fetch_data(Path('data')).refused, sep='\n')"

# The project alone is built from this repo's source and installed non-editable; dependencies stay wheel-only. The
# build fails without the SHA: the engine version names the commit.
ARG CRAWLERAI_GIT_SHA=""
COPY hatch_build.py ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra parquet --no-build --no-binary-package crawlerai --no-editable

FROM python:3.12-slim

ENV PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY alembic.ini ./
COPY migrations ./migrations

# The browser rung's Google Chrome stable (acquisition spec, "Patchright's documented browser setup"), installed as the
# Patchright README sets it up (its apt package, under /opt/google/chrome for every user), with the system libraries
# and fonts the package depends on; then the service user.
RUN patchright install --with-deps chrome && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home crawlerai
USER crawlerai

EXPOSE 8000
CMD ["uvicorn", "--factory", "crawlerai.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

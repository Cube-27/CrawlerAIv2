# The single backend image (SPEC-00 §2). Build from the repo root, naming the commit for the engine version:
#   docker build -f infra/Dockerfile --build-arg CRAWLERAI_GIT_SHA=$(git rev-parse HEAD) backend
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
WORKDIR /app

# Dependencies install from wheels only, so no third-party build script runs.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-build --no-install-project

# The project alone is built from this repo's source and installed non-editable; dependencies stay wheel-only.
# The build hook puts VERSION and the manifest's data files in the wheel (hatch_build.py), so the fetched files are
# downloaded and checked against their pinned sha256 first. Without the SHA the engine version says `unknown`.
ARG CRAWLERAI_GIT_SHA=""
COPY hatch_build.py ./
COPY data ./data
COPY src ./src
# `crawlerai data fetch` without the CLI, which needs the installed project. A refused entry is printed and left out of
# the image, which then reports it missing at run time: the GeoNames dump is rewritten daily, so its pin goes stale
# until it has a stable source (D-0311).
RUN PYTHONPATH=src python -c "from pathlib import Path; from crawlerai.core.data import fetch_data; \
    print(*fetch_data(Path('data')).refused, sep='\n')"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-build --no-binary-package crawlerai --no-editable
COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --system --no-create-home crawlerai
USER crawlerai

EXPOSE 8000
CMD ["uvicorn", "--factory", "crawlerai.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

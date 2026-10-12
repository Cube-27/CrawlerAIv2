# The single backend image (SPEC-00 §2). Build from the repo root: docker build -f infra/Dockerfile backend
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PATH=/app/.venv/bin:$PATH
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY . .
RUN uv sync --frozen

EXPOSE 8000
CMD ["uvicorn", "--factory", "crawlerai.api.app:create_app", "--host", "0.0.0.0", "--port", "8000"]

# API image. The same image runs the CLI: `docker compose run --rm app influx crawl …`.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so this layer is reused until the lockfile changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# Non-root, with a home for the caches tldextract and friends write.
RUN useradd --system --create-home --shell /usr/sbin/nologin influx
USER influx

EXPOSE 8000
CMD ["uvicorn", "influx.main:app", "--host", "0.0.0.0", "--port", "8000"]

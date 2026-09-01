# ---- Stage 1: frontend build ----
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: python runtime ----
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src/ src/
COPY data/ data/
RUN uv sync --frozen --no-dev

# Bake the embedding model into the image: startup then needs no network and
# repeat deploys are byte-identical. Model name mirrors config.py's default.
RUN uv run --no-sync python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

COPY --from=frontend /build/dist frontend/dist

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "recipe_qa.app:app", "--host", "0.0.0.0", "--port", "8000"]

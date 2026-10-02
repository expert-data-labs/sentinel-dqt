# Container for running the test suite (reproduces CI locally).

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Install dependencies first so source changes don't invalidate this layer.
COPY pyproject.toml uv.lock* ./
RUN uv sync --all-groups --no-install-project

COPY . .
RUN uv sync --all-groups

CMD ["uv", "run", "pytest"]

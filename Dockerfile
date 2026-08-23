# Reproducible environment for running Sentinel's test suite (PRD success
# metric: "the project can be run locally from documented setup steps and
# through a reproducible container environment"). Nothing to serve yet —
# Milestone 0/1 has no CLI or API — so the default command is the test
# suite; this image is for reproducing CI locally, not for deployment.

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Install dependencies before copying source, so dependency changes (not
# source changes) are what invalidate this layer's cache.
COPY pyproject.toml uv.lock* ./
RUN uv sync --all-groups --no-install-project

COPY . .
RUN uv sync --all-groups

CMD ["uv", "run", "pytest"]

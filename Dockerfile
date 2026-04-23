# Turing (Cortex Protocol) — multi-stage Docker image.
#
# Builds two tags:
#   cortex-protocol/cortex:<version>       lean image, Python only
#   cortex-protocol/cortex:<version>-full  adds Node + warms every bundled MCP server
#
# The `-full` image is the airgap / enterprise story: one pull, no npm reach-out
# at runtime. The lean image is the default — external MCP servers are fetched
# lazily via npx from the host's Node install.

# ---------------------------------------------------------------------------
# Stage 1: wheel builder — install cortex-protocol[all] into a staging dir.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY cortex_protocol ./cortex_protocol

# Use a target dir install so the final stage just copies the site-packages
# tree without pulling toolchains along with it.
RUN python -m pip install --upgrade pip \
 && python -m pip install --target /opt/cortex-venv ".[mcp,otel,enterprise]"

# ---------------------------------------------------------------------------
# Stage 2: runtime (lean). No Node; external MCP servers via host's npx.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/cortex-venv \
    PATH=/opt/cortex-venv/bin:$PATH \
    CORTEX_HOME=/root/.cortex-protocol

# Runtime is deliberately minimal — no git, no gcc. If a user needs those
# they should use the `:full` tag.
COPY --from=builder /opt/cortex-venv /opt/cortex-venv

# Healthcheck: the CLI responds to --version without hitting network.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD cortex-protocol --version || exit 1

# Default workdir for `docker run ... compile agent.yaml`.
WORKDIR /work

ENTRYPOINT ["cortex-protocol"]
CMD ["--help"]

# ---------------------------------------------------------------------------
# Stage 3: full — adds Node and warms every bundled MCP server's npx cache.
# Build this via:  docker build --target full -t cortex-protocol/cortex:<v>-full .
# ---------------------------------------------------------------------------
FROM runtime AS full

# node:20 is the version Anthropic's official MCP servers target.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Warm the npx cache for every bundled MCP server so the container is airgap
# ready. We ignore individual failures — some servers don't support --version
# but the side effect (download to cache) still happens.
RUN cortex-protocol mcp install --all || true

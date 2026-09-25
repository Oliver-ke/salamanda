FROM node:24-bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates util-linux \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /usr/local/bin/
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_PROJECT_ENVIRONMENT=/opt/agent-venv
RUN useradd --create-home --uid 10001 runner

WORKDIR /opt/agent
COPY agent/pyproject.toml agent/uv.lock agent/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent/ ./
RUN uv sync --frozen --no-dev

# The snapshot: repo cloned and dependencies installed at build time, so runs start warm.
# The tree belongs to runner (agent-run commands); .git stays root's and read-only to
# runner, because the worker runs git as root.
ARG REPO_URL=https://github.com/Oliver-ke/loop-sdlc.git
RUN git clone "$REPO_URL" /workspace/repo \
 && cd /workspace/repo && npm ci \
 && sha256sum package-lock.json | cut -d' ' -f1 > /opt/snapshot-lock.sha256 \
 && chown -R runner:runner /workspace/repo \
 && chown -R root:root /workspace/repo/.git \
 && chmod -R go-w /workspace/repo/.git \
 && git config --system --add safe.directory /workspace/repo

ENV LOOP_REPO_DIR=/workspace/repo \
    LOOP_SNAPSHOT_LOCK_FILE=/opt/snapshot-lock.sha256 \
    LOOP_COMMAND_USER=runner
EXPOSE 8080
CMD ["/opt/agent-venv/bin/python", "-m", "loop_agent", "serve", "--port", "8080"]

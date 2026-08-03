# Model Router — Docker image
# One-command deploy: docker compose up -d
FROM python:3.12-slim

WORKDIR /app

# Install package (deps pinned to secure minimums in pyproject.toml)
COPY pyproject.toml README.md LICENSE ./
COPY model_router ./model_router
RUN pip install --no-cache-dir ".[server]"

# Container-friendly defaults (overridable via env)
ENV MODEL_ROUTER_HOST=0.0.0.0 \
    MODEL_ROUTER_PORT=6060 \
    MODEL_ROUTER_DATA_DIR=/data

# Persistent memory (routing learning stats + request log)
VOLUME ["/data"]

EXPOSE 6060

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6060/health')" || exit 1

CMD ["model-router", "serve"]

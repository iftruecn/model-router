# Model Router — Docker image (v1.8.0)
# One-command deploy: docker compose up -d
FROM python:3.12-slim

WORKDIR /app

# P1-20: Copy only dependency files first for better layer caching
COPY pyproject.toml README.md LICENSE ./
# Create empty package dir so pip install works before full COPY
RUN mkdir -p model_router && \
    pip install --no-cache-dir ".[server]" || true

# Now copy the full source
COPY model_router ./model_router
RUN pip install --no-cache-dir ".[server]"

# P0-6: Run as non-root user
RUN groupadd -r modelrouter && useradd -r -g modelrouter -d /app modelrouter && \
    chown -R modelrouter:modelrouter /app
USER modelrouter

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

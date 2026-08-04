"""
FastAPI application factory for Model Router v1.0.9.

Manages application lifecycle including:
- Connection pool initialization/cleanup
- Model registry initialization (enhances agent's model capabilities)
- Persistent memory store load/save (routing learning, v1.0.2)
- Virtual API key load/save + auth middleware (v1.0.3)
- Logging setup
- Request ID tracking
- Admin API for runtime model configuration
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from model_router import __version__
from model_router.config.defaults import (
    AUTH_PUBLIC_PATHS,
    DEFAULT_HOST,
    DEFAULT_LOG_DATE_FORMAT,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PORT,
    DEFAULT_REGISTRY_MODE,
    MEMORY_DEFAULT_DATA_DIR,
    MAX_REQUEST_BODY_SIZE,
)
from model_router.core.auth import key_manager
from model_router.core.capabilities import capability_registry
from model_router.core.memory import memory_store
from model_router.providers.pool import pool
from model_router.providers.registry import model_registry

logger = logging.getLogger(__name__)


def setup_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    """
    Configure structured logging for the application.

    Replaces the v1.0 print-based logging with proper Python logging module.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_LOG_DATE_FORMAT,
    )
    # Reduce noise from httpx/uvicorn
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logger.info("Logging configured: level=%s", level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown:
    - Startup: Initialize connection pool + model registry + memory store + API keys
    - Shutdown: Persist memory + API keys + close all connections gracefully
    """
    # Startup
    logger.info("Model Router v%s starting up...", __version__)

    # 1. Initialize connection pool
    await pool.initialize()
    logger.info("Connection pool initialized")

    # 2. Initialize model registry with agent's models
    # models_config is set by create_app() and stored on app.state
    models_config = getattr(app.state, "models_config", {})
    registry_mode = getattr(app.state, "registry_mode", DEFAULT_REGISTRY_MODE)

    if models_config:
        await model_registry.initialize(
            models_config=models_config,
            mode=registry_mode,
        )
        logger.info(
            "Model registry initialized: %d models (mode=%s)",
            len(model_registry.profiles),
            model_registry.mode,
        )
    else:
        logger.warning("No models_config provided — registry will be empty")

    # 3. Load persistent memory (routing learning stats + request log)
    data_dir = getattr(app.state, "data_dir", MEMORY_DEFAULT_DATA_DIR)
    if data_dir != memory_store.data_dir:
        # Rebind data dir before first load (set via create_app/env)
        memory_store._data_dir = data_dir
    await memory_store.load()
    logger.info("Memory store loaded from %s", data_dir)

    # 4. Load virtual API keys (v1.0.3)
    if data_dir != key_manager.data_dir:
        key_manager._data_dir = data_dir
    await key_manager.load()
    if key_manager.auth_enabled:
        logger.info("API key auth ACTIVE (%d keys)", len(key_manager.list_keys()))
    else:
        logger.info("API key auth inactive (no keys configured — open access)")

    # 5. Bind capability registry to data dir + load persisted declarations
    capability_registry.bind(data_dir)
    if capability_registry.enabled:
        logger.info(
            "Agent capabilities loaded (%s, fp=%s)",
            capability_registry.agent_id, capability_registry.fingerprint,
        )

    yield

    # Shutdown
    logger.info("Model Router shutting down...")
    await memory_store.save()
    await key_manager.save()
    logger.info("Memory store + API keys persisted")
    await pool.close()
    logger.info("Shutdown complete")


def create_app(
    models_config: Optional[dict] = None,
    registry_mode: str = DEFAULT_REGISTRY_MODE,
    data_dir: Optional[str] = None,
    fallback_chain_config: Optional[dict] = None,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        models_config: The agent's models dict (from config.yaml).
                       Model Router enhances these, does not add new ones.
        registry_mode: "online", "offline", or "auto"
        data_dir: Persistent memory directory (default: ./data or
                  $MODEL_ROUTER_DATA_DIR)
        fallback_chain_config: Fallback chain mapping (from config.yaml).
                               Maps model_key -> [fallback_model_keys].

    Returns:
        FastAPI: Configured application instance
    """
    setup_logging()

    app = FastAPI(
        title="Model Router",
        description=(
            "Universal MOA (Mixture of Agents) middleware — "
            "intelligent multi-model routing for any OpenAI-compatible agent"
        ),
        version=__version__,
        lifespan=lifespan,
    )

    # Store config on app.state for lifespan access
    app.state.models_config = models_config or {}
    app.state.registry_mode = registry_mode
    app.state.data_dir = (
        data_dir
        or os.environ.get("MODEL_ROUTER_DATA_DIR")
        or MEMORY_DEFAULT_DATA_DIR
    )
    app.state.fallback_chain_config = fallback_chain_config or {}


    @app.middleware("http")
    async def body_size_limit_middleware(request: Request, call_next):
        """Reject POST/PUT requests with body exceeding MAX_REQUEST_BODY_SIZE."""
        if request.method in ("POST", "PUT"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
                return JSONResponse(
                    {"error": {"message": "Request body too large", "type": "payload_too_large"}},
                    status_code=413,
                )
        return await call_next(request)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """
        Inject unique request ID into each request.

        The request_id is:
        - Generated as UUID v4 (random)
        - Available in request.state for logging
        - Returned in X-Request-Id response header
        """
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id

        return response

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        """
        Virtual API key auth (v1.0.3, P0 #3).

        - Inactive while no keys are configured (zero-config by default)
        - Public paths (health/docs/root) always pass
        - Everything else requires ``Authorization: Bearer mr-sk-...``
        - Valid key id is attached to request.state + usage is counted
        """
        if not key_manager.auth_enabled:
            return await call_next(request)

        path = request.url.path
        if path in AUTH_PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        raw_key = (
            auth_header.removeprefix("Bearer ").strip()
            if auth_header.startswith("Bearer ")
            else ""
        )
        record = key_manager.verify(raw_key)
        if record is None:
            return JSONResponse(
                {
                    "error": {
                        "message": "Invalid or missing API key. "
                                   "Send 'Authorization: Bearer <your-key>'.",
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                    }
                },
                status_code=401,
            )

        request.state.key_id = record["key_id"]
        response = await call_next(request)

        # Lightweight per-key spend attribution (requests now, cost once
        # real provider forwarding exposes per-request pricing)
        if record["key_id"] != "__master__":
            key_manager.record_usage(record["key_id"], estimated_cost=0.0)

        return response

    # Register admin routes (runtime model configuration + learning)
    from model_router.api.admin import router as admin_router
    app.include_router(admin_router)

    # Register virtual API key management (v1.0.3)
    from model_router.api.keys import router as keys_router
    app.include_router(keys_router)

    # Register chat completions route (routing + transparency headers)
    from model_router.api.chat import router as chat_router
    app.include_router(chat_router)

    # Register cost & learning dashboard (v1.0.3)
    from model_router.api.dashboard import router as dashboard_router
    app.include_router(dashboard_router)

    @app.get("/health")
    async def health() -> dict:
        """Health check endpoint with pool, registry and memory status."""
        return {
            "status": "ok",
            "version": __version__,
            "connection_pool": pool.get_stats(),
            "registry": {
                "mode": model_registry.mode,
                "models": len(model_registry.profiles),
                "enhanced": sum(
                    1 for p in model_registry.profiles.values()
                    if p.source == "enhanced"
                ),
            },
            "memory": memory_store.get_cost_stats(),
            "auth": {"enabled": key_manager.auth_enabled},
        }

    @app.get("/v1/models")
    async def list_models() -> dict:
        """List models the agent has registered with Model Router."""
        models = []
        for key, profile in model_registry.profiles.items():
            models.append({
                "id": key,
                "name": profile.name,
                "provider": profile.provider,
                "capabilities": profile.capabilities,
                "context_window": profile.context_window,
                "supports_vision": profile.supports_vision,
                "latency_tier": profile.latency_tier,
                "selection_mode": profile.selection_mode,
                "source": profile.source,
            })
        return {
            "object": "list",
            "data": models,
        }

    @app.get("/")
    async def root() -> dict:
        """Root endpoint."""
        return {
            "service": "Model Router",
            "type": "MOA Middleware",
            "version": __version__,
            "description": "Universal multi-model routing for any OpenAI-compatible agent",
            "docs": "/docs",
            "dashboard": "/dashboard",
            "admin": "/admin/models",
            "learning": "/admin/learning",
            "preset": "/admin/preset",
            "keys": "/admin/keys",
        }

    return app


def _load_config_from_yaml() -> tuple[dict, dict]:
    """
    Load models_config and fallback_chain from config.yaml if it exists.

    Returns (models_config, fallback_chain_config).
    """
    from pathlib import Path

    config_path = Path("config.yaml")
    if not config_path.exists():
        return {}, {}

    try:
        import yaml
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        models = data.get("models", {})
        fallback_chain = data.get("fallback_chain", {})
        logger.info(
            "Loaded config.yaml: %d models, %d fallback entries",
            len(models), len(fallback_chain),
        )
        return models, fallback_chain
    except Exception as exc:
        logger.warning("Failed to load config.yaml: %s", exc)
        return {}, {}


# Default app instance (loads config.yaml if available)
_models_config, _fallback_chain_config = _load_config_from_yaml()
app = create_app(
    models_config=_models_config,
    fallback_chain_config=_fallback_chain_config,
)

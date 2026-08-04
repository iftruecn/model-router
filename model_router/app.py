"""
FastAPI application factory for Model Router v1.7.0.

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
from model_router.runtime import AppContext
from model_router.core.rate_limit import _rate_limiter
from model_router.core.security import env_key_sync, mask_key
from model_router.core.auth import key_manager
from model_router.core.capabilities import capability_registry
from model_router.core.memory import memory_store
from model_router.providers.pool import pool
from model_router.providers.registry import model_registry

logger = logging.getLogger(__name__)


def setup_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    """
    Configure structured logging for the application.

    Supports JSON structured logs (production) or text (development).
    Set MODEL_ROUTER_LOG_FORMAT=json for JSON output.
    """
    from model_router.core.logging import setup_logging as _setup
    _setup(level=level)


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


    # 6. Create AppContext container (v1.2.0)
    from model_router.core.learner import learner as global_learner, diversity_guard as global_guard
    from model_router.core.router import smart_router
    ctx = AppContext(
        router=smart_router,
        learner=global_learner,
        guard=global_guard,
        memory=memory_store,
        registry=model_registry,
        pool=pool,
        keys=key_manager,
        capabilities=capability_registry,
        models_config=models_config or {},
        fallback_chain_config=getattr(app.state, "fallback_chain_config", {}),
    )
    app.state.ctx = ctx

    # 7. Snapshot env API keys for change detection (v1.3.0)
    env_key_sync.snapshot()
    logger.info("AppContext container created (v1.2.0)")

    yield

    # Shutdown
    logger.info("Model Router shutting down...")
    await ctx.memory.save()
    await ctx.keys.save()
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
        ctx: AppContext = request.app.state.ctx
        if not ctx.keys.auth_enabled:
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
        record = ctx.keys.verify(raw_key)
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
            ctx.keys.record_usage(record["key_id"], estimated_cost=0.0)

        return response


    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        """Per-key rate limiting (v1.3.0).

        Note: runs before auth_middleware (Starlette LIFO), so we extract
        key from Authorization header directly instead of request.state.
        """
        if _rate_limiter._enabled and request.method in ("POST", "GET"):
            auth_header = request.headers.get("Authorization", "")
            raw_key = (
                auth_header.removeprefix("Bearer ").strip()
                if auth_header.startswith("Bearer ")
                else ""
            )
            # Use key hash as bucket id; anonymous if no key
            key_id = raw_key if raw_key else "anonymous"
            allowed, retry_after = _rate_limiter.check(key_id)
            if not allowed:
                return JSONResponse(
                    {
                        "error": {
                            "message": "Rate limit exceeded. Try again later.",
                            "type": "rate_limit_exceeded",
                            "retry_after": round(retry_after, 1),
                        }
                    },
                    status_code=429,
                    headers={"Retry-After": str(int(retry_after) + 1)},
                )
        return await call_next(request)

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
    async def health(request: Request) -> dict:
        """Health check endpoint with pool, registry and memory status."""
        ctx: AppContext = request.app.state.ctx
        # Check for env key changes (best-effort, non-blocking)
        changed_keys = env_key_sync.check()
        if changed_keys:
            logger.warning(
                "Env API keys changed: %s — reload config to apply",
                ", ".join(changed_keys),
            )
            env_key_sync.update_snapshot()
        return {
            "status": "ok",
            "version": __version__,
            "connection_pool": ctx.pool.get_stats(),
            "registry": {
                "mode": ctx.registry.mode,
                "models": len(ctx.registry.profiles),
                "enhanced": sum(
                    1 for p in ctx.registry.profiles.values()
                    if p.source == "enhanced"
                ),
            },
            "memory": ctx.memory.get_cost_stats(),
            "auth": {"enabled": ctx.keys.auth_enabled},
        }

    @app.get("/v1/models")
    async def list_models(request: Request) -> dict:
        """List models the agent has registered with Model Router."""
        ctx: AppContext = request.app.state.ctx
        models = []
        for key, profile in ctx.registry.profiles.items():
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
    Layered config loading for Model Router v1.7.0.

    Priority (high → low):
      1. config.yaml explicit models
      2. Environment variable API keys (auto-generate)
      3. Agent config auto-inheritance (Hermes, Claude Code, etc.)
      4. Empty defaults

    Returns (models_config, fallback_chain_config).
    """
    from pathlib import Path

    config_path = Path("config.yaml")
    models_config: dict = {}
    fallback_chain_config: dict = {}

    # Layer 1: config.yaml explicit configuration (highest priority)
    if config_path.exists():
        try:
            try:
                import yaml
                data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except ImportError:
                from model_router.config.validator import _simple_yaml_load
                data = _simple_yaml_load(str(config_path))
            models_config = data.get("models", {})
            fallback_chain_config = data.get("fallback_chain", {})
            logger.info(
                "Layer 1: Loaded config.yaml — %d models, %d fallback entries",
                len(models_config), len(fallback_chain_config),
            )
        except Exception as exc:
            logger.warning("Failed to load config.yaml: %s", exc)

    # Layer 2: Auto-generate from env vars if no models loaded
    if not models_config:
        try:
            from model_router.config.auto_config import auto_generate_config
            if auto_generate_config():
                logger.info("Layer 2: Auto-generated config.yaml from env keys")
                # Re-read the generated file
                if config_path.exists():
                    try:
                        try:
                            import yaml
                            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                        except ImportError:
                            from model_router.config.validator import _simple_yaml_load
                            data = _simple_yaml_load(str(config_path))
                        models_config = data.get("models", {})
                        fallback_chain_config = data.get("fallback_chain", {})
                    except Exception as exc:
                        logger.warning("Failed to re-read generated config: %s", exc)
        except Exception as exc:
            logger.debug("Env key auto-gen skipped: %s", exc)

    # Layer 3: Agent config auto-inheritance (zero-config startup)
    if not models_config:
        try:
            from model_router.config.auto_inherit import (
                discover_agent_config, build_models_from_agent,
            )
            agent_cfg = discover_agent_config()
            if agent_cfg:
                inherited = build_models_from_agent(agent_cfg)
                if inherited:
                    models_config = inherited
                    # Auto-generate fallback chain from tier classification
                    fallback_chain_config = _build_fallback_from_tiers(inherited)
                    logger.info(
                        "Layer 3: Inherited %d models from Agent config (%s)",
                        len(inherited),
                        ", ".join(set(m.get("provider", "?") for m in inherited.values())),
                    )
        except Exception as exc:
            logger.debug("Agent inheritance skipped: %s", exc)


    # Layer 4: Multi-agent auto-connect (v1.5.0)
    # Scan all installed agents and merge their models
    if not models_config:
        try:
            from model_router.core.agent_registry import get_agent_registry
            from model_router.config.auto_inherit import build_models_from_agent
            from model_router.config.agent_discovery import discover_all_agents

            registry = get_agent_registry(data_dir=MEMORY_DEFAULT_DATA_DIR)
            all_agents = discover_all_agents()

            for agent in all_agents:
                if registry.is_installed(agent.agent_type):
                    # Agent was installed, load its models
                    from model_router.config.auto_inherit.detector import (
                        _load_yaml_safe, parse_agent_providers,
                    )
                    fmt = "json" if agent.config_path.suffix == ".json" else "yaml"
                    cfg = _load_yaml_safe(agent.config_path, fmt)
                    if cfg:
                        providers = parse_agent_providers(cfg)
                        for prov in providers:
                            for model_id in prov.get("models", []):
                                model_key = model_id
                                if model_key not in models_config:
                                    models_config[model_key] = {
                                        "model": model_id,
                                        "provider": prov.get("name", agent.agent_type),
                                        "api_key": prov.get("api_key", ""),
                                        "base_url": prov.get("base_url", ""),
                                        "tier": "pro",
                                    }
                    logger.info(
                        "Layer 4: Loaded %d models from installed agent '%s'",
                        len(models_config), agent.agent_type,
                    )
        except Exception as exc:
            logger.debug("Multi-agent auto-connect skipped: %s", exc)

    if not models_config:
        logger.warning(
            "No models configured — starting with EMPTY registry. "
            "Router will return errors for all chat requests. "
            "Check config.yaml, environment variables, or Agent config path."
        )

    return models_config, fallback_chain_config


def _build_fallback_from_tiers(models_config: dict) -> dict:
    """
    Auto-generate fallback chain from tier-classified models.

    pro-tier models fall back to flash-tier within same provider,
    then cross-provider flash as last resort.
    """
    tiers: dict[str, list[str]] = {"pro": [], "flash": []}
    providers: dict[str, list[str]] = {}

    for key, cfg in models_config.items():
        tier = cfg.get("tier", "pro")
        provider = cfg.get("provider", "unknown")
        tiers.setdefault(tier, []).append(key)
        providers.setdefault(provider, []).append(key)

    chain = {}
    # pro models → same-provider flash → any flash
    for pro_key in tiers.get("pro", []):
        pro_provider = models_config[pro_key].get("provider", "")
        same_prov_flash = [
            k for k in tiers.get("flash", [])
            if models_config[k].get("provider") == pro_provider
        ]
        other_flash = [
            k for k in tiers.get("flash", [])
            if models_config[k].get("provider") != pro_provider
        ]
        chain[pro_key] = same_prov_flash + other_flash

    # flash models → same-provider alternatives
    for flash_key in tiers.get("flash", []):
        flash_provider = models_config[flash_key].get("provider", "")
        others = [
            k for k in tiers.get("flash", [])
            if k != flash_key and models_config[k].get("provider") == flash_provider
        ]
        chain[flash_key] = others

    return chain


# Default app instance (loads config.yaml if available)
_models_config, _fallback_chain_config = _load_config_from_yaml()
app = create_app(
    models_config=_models_config,
    fallback_chain_config=_fallback_chain_config,
)

"""
Admin API for runtime model configuration and learning control.

Allows agents and users to configure model selection modes,
routing presets, and submit feedback — no config file editing needed.

Multilingual: Supports EN, ZH, JA, KO, ES, FR, DE.

Endpoints:
    GET  /admin/models           — List all models with current config
    PUT  /admin/models/{id}      — Update a model's selection_mode
    POST /admin/models/batch     — Batch update multiple models
    GET  /admin/models/stats     — Routing statistics
    GET  /admin/learning         — Learning + cost statistics (v1.2.0)
    POST /admin/feedback/{rid}   — Explicit feedback for a request (v1.0.2)
    GET  /admin/preset           — Current routing preset (v1.0.2)
    PUT  /admin/preset/{name}    — Set routing preset (v1.0.2)
    GET  /admin/evaluate         — Offline evaluation report (v1.0.4)
    GET  /admin/capabilities     — Agent capability declarations (v1.0.4)
    PUT  /admin/capabilities     — Declare agent capabilities (v1.0.4)
    GET  /admin/explain          — Why-this-model: ?request_id=X or ?message=Y (v1.1.0)
    POST /admin/explain          — Why-this-model dry-run with full messages (v1.1.0)
    POST /admin/config/validate  — Validate config.yaml (v1.1.0)
    PUT  /admin/capabilities     — Declare agent capabilities (v1.0.4)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from model_router.config.defaults import ROUTING_PRESETS
from model_router.config.validator import validate_config
from model_router.runtime import AppContext
from model_router.core.security import env_key_sync, mask_key, mask_config_keys
from model_router.core.cache import semantic_cache
from model_router.core.capabilities import capability_registry
from model_router.core.evaluator import offline_evaluator
from model_router.core.learner import diversity_guard, learner
from model_router.core.memory import memory_store
from model_router.core.router import smart_router
from model_router.locales.i18n import t, init_language
from model_router.providers.registry import model_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ------------------------------------------------------------------
# Request/Response models
# ------------------------------------------------------------------

class ModelUpdateRequest(BaseModel):
    """Request body for updating a model's config."""
    selection_mode: str = Field(
        ...,
        pattern="^(auto|manual)$",
        description="'auto' = router can select, 'manual' = user must specify",
    )
    lang: str = Field(
        default="en",
        description="Response language (en/zh/ja/ko/es/fr/de)",
    )


class BatchUpdateRequest(BaseModel):
    """Request body for batch updating multiple models."""
    updates: dict[str, str] = Field(
        ...,
        description="Dict of model_id -> selection_mode ('auto' or 'manual')",
        examples=[{"dall-e-3": "manual", "gpt-4o-mini": "auto"}],
    )
    lang: str = Field(
        default="en",
        description="Response language (en/zh/ja/ko/es/fr/de)",
    )


class FeedbackRequest(BaseModel):
    """Request body for explicit feedback on a completed request."""
    feedback: str = Field(
        ...,
        pattern="^(positive|negative)$",
        description="'positive' = user satisfied, 'negative' = user unsatisfied",
    )
    lang: str = Field(default="en")


class ModelInfoResponse(BaseModel):
    """Model info with current configuration."""
    id: str
    name: str
    provider: str = ""
    selection_mode: str
    supports_vision: bool = False
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    latency_tier: str = "medium"
    capabilities: dict = {}
    source: str = "local"


# ------------------------------------------------------------------
# Model configuration endpoints
# ------------------------------------------------------------------

@router.get("/models", response_model=list[ModelInfoResponse])
async def list_models() -> list[dict]:
    """
    List all registered models with their current configuration.

    Returns model details including selection_mode (auto/manual).
    """
    result = []
    for key, profile in model_registry.profiles.items():
        result.append({
            "id": key,
            "name": profile.name,
            "provider": profile.provider,
            "selection_mode": profile.selection_mode,
            "supports_vision": profile.supports_vision,
            "cost_per_1k_input": profile.cost_per_1k_input,
            "cost_per_1k_output": profile.cost_per_1k_output,
            "latency_tier": profile.latency_tier,
            "capabilities": profile.capabilities,
            "source": profile.source,
        })
    return result


@router.put("/models/{model_id}")
async def update_model(model_id: str, req: ModelUpdateRequest) -> dict:
    """
    Update a single model's selection_mode.

    Example:
        PUT /admin/models/dall-e-3
        {"selection_mode": "manual", "lang": "zh"}

    This prevents the router from auto-selecting dall-e-3,
    avoiding unexpected costs from image generation.
    """
    # Set response language
    init_language(req.lang)

    profile = model_registry.get_profile(model_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=t(
                "error.model_not_found",
                model_id=model_id,
                available=str(model_registry.list_models()),
            ),
        )

    old_mode = profile.selection_mode
    profile.selection_mode = req.selection_mode

    # Build localized mode description
    if req.selection_mode == "manual":
        mode_desc = t("api.excluded_from_auto")
    else:
        mode_desc = t("api.included_in_auto")

    logger.info(
        "Model %s selection_mode changed: %s -> %s",
        model_id, old_mode, req.selection_mode,
    )

    return {
        "id": model_id,
        "old_mode": old_mode,
        "new_mode": req.selection_mode,
        "message": t("api.mode_changed", model_id=model_id, mode_desc=mode_desc),
    }


@router.post("/models/batch")
async def batch_update(req: BatchUpdateRequest) -> dict:
    """
    Batch update multiple models' selection_mode.

    Example:
        POST /admin/models/batch
        {
            "updates": {
                "dall-e-3": "manual",
                "sora": "manual",
                "gpt-4o-mini": "auto"
            },
            "lang": "zh"
        }

    Returns summary of changes.
    """
    # Set response language
    init_language(req.lang)

    changed = []
    errors = []

    for model_id, mode in req.updates.items():
        profile = model_registry.get_profile(model_id)
        if not profile:
            errors.append(t("error.model_not_found", model_id=model_id, available=""))
            continue

        if mode not in ("auto", "manual"):
            errors.append(t("error.invalid_mode", mode=mode))
            continue

        old_mode = profile.selection_mode
        if old_mode != mode:
            profile.selection_mode = mode
            changed.append({"id": model_id, "from": old_mode, "to": mode})

    auto_count = sum(1 for p in model_registry.profiles.values() if p.selection_mode == "auto")
    manual_count = len(model_registry.profiles) - auto_count

    logger.info(
        "Batch update: %d changed, %d errors. Now: %d auto, %d manual",
        len(changed), len(errors), auto_count, manual_count,
    )

    return {
        "changed": changed,
        "errors": errors,
        "summary": {
            "total": len(model_registry.profiles),
            "auto": auto_count,
            "manual": manual_count,
        },
    }


@router.get("/models/stats")
async def routing_stats() -> dict:
    """
    Get routing statistics: how many models are auto vs manual,
    and which models are available for auto-routing.
    """
    profiles = model_registry.profiles

    auto_models = [
        {"id": k, "name": p.name, "cost": p.cost_per_1k_input}
        for k, p in profiles.items()
        if p.selection_mode == "auto"
    ]
    manual_models = [
        {"id": k, "name": p.name, "cost": p.cost_per_1k_input}
        for k, p in profiles.items()
        if p.selection_mode == "manual"
    ]

    return {
        "total_models": len(profiles),
        "auto_count": len(auto_models),
        "manual_count": len(manual_models),
        "auto_models": auto_models,
        "manual_models": manual_models,
        "registry_mode": model_registry.mode,
    }


# ------------------------------------------------------------------
# Learning endpoints (v1.0.2)
# ------------------------------------------------------------------

@router.get("/learning")
async def learning_stats(request: Request) -> dict:
    """
    Learning + cost statistics.

    Shows Gaussian TS progress (shadow/active mode), routing diversity
    guard status, tracked (task, model) pairs, and quantified cost savings.
    """
    ctx: AppContext = request.app.state.ctx
    # Feedback stats from request log (v1.2.0)
    all_requests = ctx.memory.recent_requests(limit=10000)
    feedback_entries = [r for r in all_requests if r.get("feedback")]
    feedback_positive = sum(1 for r in feedback_entries if r.get("feedback") == "positive")
    feedback_negative = sum(1 for r in feedback_entries if r.get("feedback") == "negative")
    recent_feedback = [
        {
            "request_id": r.get("request_id", "")[:8],
            "task": r.get("task", ""),
            "model": r.get("final_model", ""),
            "feedback": r.get("feedback", ""),
        }
        for r in reversed(all_requests) if r.get("feedback")
    ][:20]

    return {
        "learning": ctx.learner.get_stats(),
        "diversity": ctx.guard.get_stats(),
        "cost": ctx.memory.get_cost_stats(),
        "recent_requests": ctx.memory.recent_requests(limit=10),
        "feedback": {
            "total": len(feedback_entries),
            "positive": feedback_positive,
            "negative": feedback_negative,
            "recent": recent_feedback,
        },
    }


@router.post("/feedback/{request_id}")
async def submit_feedback(request_id: str, req: FeedbackRequest, request: Request) -> dict:
    """
    Submit explicit feedback for a completed request.

    Attribution (Hermes review): feedback is credited to the model that
    produced the final answer; models abandoned by fallback receive a
    mild penalty.

    Example:
        POST /admin/feedback/9f2c...  {"feedback": "positive"}
    """
    init_language(req.lang)
    ctx: AppContext = request.app.state.ctx

    entry = ctx.memory.get_request(request_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"Request {request_id} not found in log (ring buffer holds last "
                   f"{len(memory_store.recent_requests(1000))} entries)",
        )

    positive = req.feedback == "positive"
    await ctx.learner.apply_feedback(
        task=entry.get("task", "chat"),
        final_model=entry.get("final_model", ""),
        failed_models=entry.get("failed_models", []),
        positive=positive,
    )
    # Mark request log entry with feedback (for dashboard visualization)
    entry["feedback"] = req.feedback
    await ctx.memory.save()

    logger.info(
        "Feedback %s for request %s -> model %s",
        req.feedback, request_id, entry.get("final_model"),
    )

    return {
        "request_id": request_id,
        "feedback": req.feedback,
        "attributed_model": entry.get("final_model"),
        "task": entry.get("task"),
        "message": "Feedback recorded and learned",
    }


# ------------------------------------------------------------------
# Routing preset endpoints (v1.0.2)
# ------------------------------------------------------------------

@router.get("/preset")
async def get_preset() -> dict:
    """Get current routing preset and available options."""
    return {
        "current": smart_router.preset,
        "available": list(ROUTING_PRESETS.keys()),
        "descriptions": {
            "intelligence": "Prioritize answer quality, cost-insensitive",
            "balance": "Balanced quality / cost / speed (default)",
            "cost": "Strongly prefer cheaper models",
        },
    }


@router.put("/preset/{name}")
async def set_preset(name: str, lang: str = "en") -> dict:
    """
    Set the global routing preset: intelligence / balance / cost.

    Per-request override is still possible via "routing_preset" field
    in the chat completions body.
    """
    init_language(lang)
    if not smart_router.set_preset(name):
        raise HTTPException(
            status_code=404,
            detail=f"Unknown preset '{name}'. Available: {list(ROUTING_PRESETS.keys())}",
        )
    return {"preset": smart_router.preset, "message": f"Routing preset set to '{name}'"}


# ------------------------------------------------------------------
# Offline evaluation endpoints (v1.0.4)
# ------------------------------------------------------------------

@router.get("/evaluate")
async def evaluate_learning(request: Request, limit: int = 1000) -> dict:
    """
    Offline evaluation report: replay the request log and quantify
    how much self-learning improved routing (read-only, no mutation).
    """
    ctx: AppContext = request.app.state.ctx
    from model_router.core.evaluator import OfflineEvaluator
    ev = OfflineEvaluator(memory=ctx.memory)
    return ev.evaluate(limit=limit)


# ------------------------------------------------------------------
# Agent capability declaration endpoints (v1.0.4)
# ------------------------------------------------------------------

class CapabilitiesRequest(BaseModel):
    """Request body declaring what the host agent can lend us."""
    capabilities: dict[str, Any] = Field(
        default_factory=dict,
        description="Map of capability name -> {type, endpoint, path, ...}; "
                    "send an empty map to retract all declarations",
        examples=[{
            "vector_db": {"type": "chroma", "endpoint": "http://localhost:8000"},
            "memory": {"type": "markdown_files", "path": "F:/AI/knowledge"},
        }],
    )


@router.get("/capabilities")
async def get_capabilities() -> dict:
    """
    Show the adapter-layer status: which agent capabilities are declared
    and which enhancement points are enabled (read-only borrowing).
    """
    return capability_registry.get_status()


@router.put("/capabilities")
async def put_capabilities(req: CapabilitiesRequest) -> dict:
    """
    Declare (or replace) the host agent's capabilities. Static declaration
    only in v1.0.4 — actual borrowing hooks arrive in v1.1+.

    Sending an empty capabilities map retracts all declarations.
    """
    declared = capability_registry.declare(req.capabilities)
    logger.info("Capabilities declared: %s", declared)
    return {
        "declared": declared,
        "count": len(declared),
        "status": capability_registry.get_status(),
    }




# ------------------------------------------------------------------
# Why-this-model explanation endpoint (v1.1.0)
# ------------------------------------------------------------------

@router.get("/explain")
async def explain_routing_get(
    request_id: str = "",
    message: str = "",
) -> dict:
    """
    Why-this-model — GET for browser use.

    Two modes:
    - GET /admin/explain?request_id=abc123  → look up past request
    - GET /admin/explain?message=hello      → dry-run routing (no API calls)

    Returns the full scoring breakdown: top candidates, scores, and per-factor
    decomposition (capability match, cost, speed, learned contribution).
    """
    # Mode 1: Look up past request by ID
    if request_id:
        entry = memory_store.get_request(request_id)
        if entry is None:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail=f"Request {request_id} not found in log",
            )
        return {
            "request_id": request_id,
            "model": entry.get("final_model", ""),
            "task": entry.get("task", "chat"),
            "preset": entry.get("preset", "balance"),
            "routing_mode": entry.get("routing_mode", "static"),
            "top_candidates": entry.get("top_candidates", []),
            "candidates": entry.get("candidates", []),
            "failed_models": entry.get("failed_models", []),
            "estimated_cost": entry.get("estimated_cost", 0.0),
            "baseline_cost": entry.get("baseline_cost", 0.0),
            "cost": entry.get("cost", 0.0),
            "latency_ms": entry.get("latency_ms", 0.0),
            "prompt_tokens": entry.get("prompt_tokens", 0),
            "completion_tokens": entry.get("completion_tokens", 0),
        }

    # Mode 2: Dry-run routing with a single message
    if message:
        messages = [{"role": "user", "content": message}]
        models_config = {}
        for key, profile in model_registry.profiles.items():
            models_config[key] = {
                "enabled": profile.selection_mode == "auto",
                "capabilities": profile.capabilities,
            }
        routing = await smart_router.route(
            messages=messages,
            models_config=models_config,
            request_data={"messages": messages},
            request_id=None,  # dry-run: don't log
        )
        return {
            "model": routing.model_key,
            "model_name": routing.model_name,
            "score": routing.score,
            "reason": routing.reason,
            "task": routing.features.get("primary_domain", "chat") if routing.features else "chat",
            "preset": routing.preset,
            "routing_mode": routing.routing_mode,
            "top_candidates": routing.top_candidates,
            "candidates_scored": routing.candidates_scored,
            "estimated_cost": routing.estimated_cost,
            "baseline_cost": routing.baseline_cost,
            "learned_contribution": routing.learned_contribution,
            "dry_run": True,
        }

    from fastapi import HTTPException
    raise HTTPException(
        status_code=400,
        detail="Provide 'request_id' (lookup) or 'message' (dry-run)",
    )


@router.post("/explain")
async def explain_routing_post(request: Request) -> dict:
    """
    Dry-run routing with full message array.

    POST /admin/explain  {"messages": [{"role":"user","content":"..."}]}

    Does NOT make any API calls — only runs the routing decision locally.
    """
    try:
        body = await request.json()
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = body.get("messages")
    if not messages:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Provide 'messages' array for dry-run routing",
        )

    models_config = {}
    for key, profile in model_registry.profiles.items():
        models_config[key] = {
            "enabled": profile.selection_mode == "auto",
            "capabilities": profile.capabilities,
        }
    routing = await smart_router.route(
        messages=messages,
        models_config=models_config,
        request_data={"messages": messages},
        request_id=None,  # dry-run: don't log
    )
    return {
        "model": routing.model_key,
        "model_name": routing.model_name,
        "score": routing.score,
        "reason": routing.reason,
        "task": routing.features.get("primary_domain", "chat") if routing.features else "chat",
        "preset": routing.preset,
        "routing_mode": routing.routing_mode,
        "top_candidates": routing.top_candidates,
        "candidates_scored": routing.candidates_scored,
        "estimated_cost": routing.estimated_cost,
        "baseline_cost": routing.baseline_cost,
        "learned_contribution": routing.learned_contribution,
        "dry_run": True,
    }



# ------------------------------------------------------------------
# Config validation endpoint (v1.1.0)
# ------------------------------------------------------------------

@router.post("/config/validate")
async def validate_config_endpoint(request: Request) -> dict:
    """
    Validate a Model Router config (YAML body or JSON body).

    Returns validation result with errors and warnings.
    """
    content_type = request.headers.get("content-type", "")

    try:
        if "yaml" in content_type or "text" in content_type:
            body = await request.body()
            text = body.decode("utf-8")
            # Try PyYAML first
            try:
                import yaml
                config = yaml.safe_load(text) or {}
            except ImportError:
                # Fallback: treat as JSON
                import json
                config = json.loads(text)
        else:
            config = await request.json()
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Failed to parse config: {exc}")

    result = validate_config(config)
    return result.to_dict()


# ------------------------------------------------------------------
# Semantic cache endpoints (FR-Qoder-v2-platform §FR-P1)
# ------------------------------------------------------------------

class CacheSeedRequest(BaseModel):
    """Pre-seed a known question/answer pair into the semantic cache."""
    messages: list = Field(..., description="Chat messages of the question")
    response: dict = Field(..., description="OpenAI-shaped answer to serve on hit")
    model: str = Field(default="", description="Model that produced the answer")


@router.get("/cache")
async def cache_stats() -> dict:
    """Semantic cache statistics (entries / hit rate / thresholds)."""
    return semantic_cache.get_stats()


@router.delete("/cache")
async def cache_clear() -> dict:
    """Drop all cached entries."""
    cleared = semantic_cache.clear()
    logger.info("Semantic cache cleared (%d entries)", cleared)
    return {"cleared": cleared}


@router.post("/cache/seed")
async def cache_seed(req: CacheSeedRequest) -> dict:
    """
    Pre-seed the cache with a known Q/A pair. Useful while provider
    forwarding is pending — agents can populate answers themselves.
    """
    stored = await semantic_cache.async_store(req.messages, req.response, model=req.model)
    return {
        "stored": stored,
        "key": semantic_cache.build_key(req.messages) if stored else "",
        "stats": semantic_cache.get_stats(),
    }


@router.get("/config/keys")
async def list_config_keys(request: Request) -> dict:
    """
    List configured API keys (masked) for security audit.

    Returns masked keys — never exposes actual values.
    """
    ctx: AppContext = request.app.state.ctx
    models_config = ctx.models_config
    result = {}
    for key, cfg in models_config.items():
        raw_key = cfg.get("api_key", "")
        result[key] = {
            "name": cfg.get("name", key),
            "base_url": cfg.get("base_url", ""),
            "api_key_masked": mask_key(raw_key) if raw_key else "(not set)",
            "model": cfg.get("model", key),
            "tier": cfg.get("tier", "pro"),
        }
    return result


@router.post("/config/sync-keys")
async def sync_env_keys(request: Request) -> dict:
    """
    Check environment variables for API key changes and reload.

    If agent's API key has changed (env var updated), this picks up
    the new key and updates the in-memory config.

    Returns which keys changed and whether config was reloaded.
    """
    ctx: AppContext = request.app.state.ctx
    changed = env_key_sync.check()

    if not changed:
        return {"changed": [], "reloaded": False, "message": "No changes detected"}

    # Re-scan env vars
    from model_router.config.auto_config import scan_env_keys, KNOWN_KEYS
    new_keys = scan_env_keys()

    updated_models = []
    for env_var in changed:
        base_url = KNOWN_KEYS.get(env_var, "")
        new_key_value = new_keys.get(env_var, "")

        # Update models that use this provider
        for model_key, model_cfg in ctx.models_config.items():
            if model_cfg.get("base_url", "") == base_url:
                if new_key_value:
                    model_cfg["api_key"] = new_key_value
                    updated_models.append(model_key)
                    logger.info(
                        "Updated API key for %s (%s)",
                        model_key, mask_key(new_key_value),
                    )
                else:
                    logger.warning(
                        "Key removed for %s (env %s deleted)",
                        model_key, env_var,
                    )

    env_key_sync.update_snapshot()

    return {
        "changed": changed,
        "reloaded": len(updated_models) > 0,
        "updated_models": updated_models,
        "message": (
            f"Updated {len(updated_models)} model(s)"
            if updated_models
            else "No models updated"
        ),
    }


@router.get("/admin/agents")
async def admin_agents(request: Request) -> dict:
    """Agent registry stats (v1.5.0)."""
    from model_router.core.agent_registry import get_agent_registry
    registry = get_agent_registry()
    stats = registry.get_agent_stats()
    return {"agents": stats}


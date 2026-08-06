"""
Admin API for runtime model configuration and learning control (v1.8.0).

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
from fastapi.responses import HTMLResponse
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
                   f"{len(ctx.memory.recent_requests(1000))} entries)",
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
    # P1-12: use ctx.memory instead of module-level singleton
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


@router.get("/agents")
async def admin_agents(request: Request) -> dict:
    """Agent registry stats (v1.5.0).
    
    P1-1 fix: use AppContext for consistency with other endpoints.
    """
    ctx: AppContext = request.app.state.ctx
    if ctx.agent_registry is None:
        return {"agents": []}
    stats = ctx.agent_registry.get_agent_stats()
    return {"agents": stats}


# ------------------------------------------------------------------
# Admin UI (v1.8.0)
# ------------------------------------------------------------------

_ADMIN_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Model Router — Admin</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0a0a0f;color:#e0e0e0;padding:20px;max-width:1200px;margin:0 auto}
h1{font-size:1.5em;margin-bottom:8px}
h2{font-size:1.2em;margin:24px 0 12px;color:#7eb8ff;border-bottom:1px solid #1a1a2e;padding-bottom:6px}
.sub{color:#888;font-size:0.85em;margin-bottom:20px}
.sub a{color:#7eb8ff;text-decoration:none}
.sub a:hover{text-decoration:underline}
.card{background:#12121a;border:1px solid #1a1a2e;border-radius:8px;padding:16px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:0.9em}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid #1a1a2e}
th{color:#888;font-weight:500;font-size:0.8em;text-transform:uppercase}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.8em;font-weight:500}
.badge-auto{background:#1a3a1a;color:#4caf50}
.badge-manual{background:#3a1a1a;color:#f44336}
.btn{padding:6px 14px;border:1px solid #333;border-radius:4px;background:#1a1a2e;color:#e0e0e0;cursor:pointer;font-size:0.85em;transition:all .15s}
.btn:hover{background:#252540;border-color:#555}
.btn-active{background:#1a3a1a;border-color:#4caf50;color:#4caf50}
.btn-sm{padding:4px 10px;font-size:0.8em}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px}
.stat{background:#12121a;border:1px solid #1a1a2e;border-radius:8px;padding:14px;text-align:center}
.stat .label{color:#888;font-size:0.75em;text-transform:uppercase;margin-bottom:4px}
.stat .value{font-size:1.4em;font-weight:600}
.green{color:#4caf50}.blue{color:#2196f3}.orange{color:#ff9800}.red{color:#f44336}
.preset-btn{margin-right:8px}
.preset-btn.active{background:#1a3a1a;border-color:#4caf50;color:#4caf50}
#toast{position:fixed;bottom:20px;right:20px;background:#1a3a1a;color:#4caf50;padding:10px 20px;border-radius:6px;display:none;font-size:0.9em;z-index:999}
.lang-bar{text-align:right;margin-bottom:12px}
.lang-bar select{background:#12121a;color:#e0e0e0;border:1px solid #333;border-radius:4px;padding:4px 8px;font-size:0.85em}
</style>
</head>
<body>
<div class="lang-bar">
  <select id="lang_selector" onchange="setLang(this.value)">
    <option value="en">English</option>
    <option value="zh">中文</option>
    <option value="ja">日本語</option>
    <option value="ko">한국어</option>
    <option value="es">Español</option>
    <option value="fr">Français</option>
    <option value="de">Deutsch</option>
  </select>
</div>
<h1 data-i18n="title">Model Router — Admin</h1>
<div class="sub">
  <a href="/dashboard" data-i18n="dashboard">Dashboard</a> &middot;
  <a href="/docs" data-i18n="api_docs">API Docs</a> &middot;
  <a href="/admin/models" data-i18n="json_api">JSON API</a>
</div>

<!-- Stats -->
<h2 data-i18n="overview">Overview</h2>
<div class="stats">
  <div class="stat"><div class="label" data-i18n="total_models">Total Models</div><div class="value blue" id="total_models">—</div></div>
  <div class="stat"><div class="label">Auto</div><div class="value green" id="auto_count">—</div></div>
  <div class="stat"><div class="label">Manual</div><div class="value orange" id="manual_count">—</div></div>
  <div class="stat"><div class="label" data-i18n="current_preset">Current Preset</div><div class="value blue" id="current_preset">—</div></div>
</div>

<!-- Models -->
<h2 data-i18n="models">Models</h2>
<div class="card">
  <table>
    <thead><tr><th data-i18n="th_model">Model</th><th data-i18n="th_provider">Provider</th><th data-i18n="th_mode">Mode</th><th data-i18n="th_cost_in">Cost/1K In</th><th data-i18n="th_cost_out">Cost/1K Out</th><th data-i18n="th_latency">Latency</th><th data-i18n="th_action">Action</th></tr></thead>
    <tbody id="models_body"><tr><td colspan="7" style="color:#888" data-i18n="loading">Loading...</td></tr></tbody>
  </table>
</div>

<!-- Presets -->
<h2 data-i18n="routing_preset">Routing Preset</h2>
<div class="card" id="preset_card">
  <div style="color:#888" data-i18n="loading">Loading...</div>
</div>

<!-- Cache -->
<h2 data-i18n="semantic_cache">Semantic Cache</h2>
<div class="stats" id="cache_stats">
  <div class="stat"><div class="label" data-i18n="entries">Entries</div><div class="value" id="cache_entries">—</div></div>
  <div class="stat"><div class="label" data-i18n="hit_rate">Hit Rate</div><div class="value green" id="cache_hit_rate">—</div></div>
  <div class="stat"><div class="label" data-i18n="total_hits">Total Hits</div><div class="value blue" id="cache_hits">—</div></div>
  <div class="stat"><div class="label" data-i18n="total_queries">Total Queries</div><div class="value" id="cache_queries">—</div></div>
</div>

<!-- Learning -->
<h2 data-i18n="learning">Learning</h2>
<div class="stats" id="learning_stats">
  <div class="stat"><div class="label" data-i18n="total_feedback">Total Feedback</div><div class="value" id="total_feedback">—</div></div>
  <div class="stat"><div class="label" data-i18n="positive">Positive</div><div class="value green" id="positive_fb">—</div></div>
  <div class="stat"><div class="label" data-i18n="negative">Negative</div><div class="value red" id="negative_fb">—</div></div>
  <div class="stat"><div class="label" data-i18n="samples_learned">Samples Learned</div><div class="value blue" id="samples_learned">—</div></div>
</div>

<div id="toast"></div>

<script>
const I18N={
en:{title:"Model Router \u2014 Admin",dashboard:"Dashboard",api_docs:"API Docs",json_api:"JSON API",overview:"Overview",total_models:"Total Models",current_preset:"Current Preset",models:"Models",routing_preset:"Routing Preset",semantic_cache:"Semantic Cache",learning:"Learning",th_model:"Model",th_provider:"Provider",th_mode:"Mode",th_cost_in:"Cost/1K In",th_cost_out:"Cost/1K Out",th_latency:"Latency",th_action:"Action",entries:"Entries",hit_rate:"Hit Rate",total_hits:"Total Hits",total_queries:"Total Queries",total_feedback:"Total Feedback",positive:"Positive",negative:"Negative",samples_learned:"Samples Learned",loading:"Loading...",set_manual:"Set Manual",set_auto:"Set Auto",language:"Language"},
zh:{title:"Model Router \u2014 \u7ba1\u7406",dashboard:"\u4eea\u8868\u76d8",api_docs:"API \u6587\u6863",json_api:"JSON API",overview:"\u6982\u89c8",total_models:"\u6a21\u578b\u603b\u6570",current_preset:"\u5f53\u524d\u9884\u8bbe",models:"\u6a21\u578b",routing_preset:"\u8def\u7531\u9884\u8bbe",semantic_cache:"\u8bed\u4e49\u7f13\u5b58",learning:"\u5b66\u4e60",th_model:"\u6a21\u578b",th_provider:"\u63d0\u4f9b\u5546",th_mode:"\u6a21\u5f0f",th_cost_in:"\u8d39\u7528/1K \u8f93\u5165",th_cost_out:"\u8d39\u7528/1K \u8f93\u51fa",th_latency:"\u5ef6\u8fdf",th_action:"\u64cd\u4f5c",entries:"\u6761\u76ee\u6570",hit_rate:"\u547d\u4e2d\u7387",total_hits:"\u603b\u547d\u4e2d",total_queries:"\u603b\u67e5\u8be2",total_feedback:"\u603b\u53cd\u9988",positive:"\u6b63\u9762",negative:"\u8d1f\u9762",samples_learned:"\u5df2\u5b66\u4e60\u6837\u672c",loading:"\u52a0\u8f7d\u4e2d...",set_manual:"\u2192 \u624b\u52a8",set_auto:"\u2192 \u81ea\u52a8",language:"\u8bed\u8a00"},
ja:{title:"Model Router \u2014 \u7ba1\u7406",dashboard:"\u30c0\u30c3\u30b7\u30e5\u30dc\u30fc\u30c9",api_docs:"API\u30c9\u30ad\u30e5\u30e1\u30f3\u30c8",json_api:"JSON API",overview:"\u6982\u8981",total_models:"\u30e2\u30c7\u30eb\u7dcf\u6570",current_preset:"\u73fe\u5728\u306e\u30d7\u30ea\u30bb\u30c3\u30c8",models:"\u30e2\u30c7\u30eb",routing_preset:"\u30eb\u30fc\u30c6\u30a3\u30f3\u30b0\u30d7\u30ea\u30bb\u30c3\u30c8",semantic_cache:"\u30bb\u30de\u30f3\u30c6\u30a3\u30c3\u30af\u30ad\u30e3\u30c3\u30b7\u30e5",learning:"\u5b66\u7fd2",th_model:"\u30e2\u30c7\u30eb",th_provider:"\u30d7\u30ed\u30d0\u30a4\u30c0\u30fc",th_mode:"\u30e2\u30fc\u30c9",th_cost_in:"\u30b3\u30b9\u30c8/1K \u5165\u529b",th_cost_out:"\u30b3\u30b9\u30c8/1K \u51fa\u529b",th_latency:"\u30ec\u30a4\u30c6\u30f3\u30b7",th_action:"\u64cd\u4f5c",entries:"\u30a8\u30f3\u30c8\u30ea\u30fc\u6570",hit_rate:"\u30d2\u30c3\u30c8\u7387",total_hits:"\u30c8\u30fc\u30bf\u30eb\u30d2\u30c3\u30c8",total_queries:"\u30c8\u30fc\u30bf\u30eb\u30af\u30a8\u30ea",total_feedback:"\u30c8\u30fc\u30bf\u30eb\u30d5\u30a3\u30fc\u30c9\u30d0\u30c3\u30af",positive:"\u80af\u5b9a",negative:"\u5426\u5b9a",samples_learned:"\u5b66\u7fd2\u30b5\u30f3\u30d7\u30eb\u6570",loading:"\u8aad\u307f\u8fbc\u307f\u4e2d...",set_manual:"\u2192 \u624b\u52d5",set_auto:"\u2192 \u81ea\u52d5",language:"\u8a00\u8a9e"},
ko:{title:"Model Router \u2014 \uad00\ub9ac",dashboard:"\ub300\uc2dc\ubcf4\ub4dc",api_docs:"API \ubb38\uc11c",json_api:"JSON API",overview:"\uac1c\uc694",total_models:"\ubaa8\ub378 \ucd1d \uc218",current_preset:"\ud604\uc7ac \ud504\ub9ac\uc14b",models:"\ubaa8\ub378",routing_preset:"\ub77c\uc6b0\ud305 \ud504\ub9ac\uc14b",semantic_cache:"\uc138\ub9cc\ud2f1 \uce90\uc2dc",learning:"\ud559\uc2b5",th_model:"\ubaa8\ub378",th_provider:"\uc81c\uacf5\uc790",th_mode:"\ubaa8\ub4dc",th_cost_in:"\ube44\uc6a9/1K \uc785\ub825",th_cost_out:"\ube44\uc6a9/1K \ucd9c\ub825",th_latency:"\ub808\uc774\ud150\uc2dc",th_action:"\uc791\uc5c5",entries:"\ud56d\ubaa9 \uc218",hit_rate:"\ud788\ud2b8\uc728",total_hits:"\ucd1d \ud788\ud2b8",total_queries:"\ucd1d \ucffc\ub9ac",total_feedback:"\ucd1d \ud53c\ub4dc\ubc31",positive:"\uae0d\uc815",negative:"\ubd80\uc815",samples_learned:"\ud559\uc2b5 \uc0d8\ud50c",loading:"\ub85c\ub529 \uc911...",set_manual:"\u2192 \uc218\ub3d9",set_auto:"\u2192 \uc790\ub3d9",language:"\uc5b8\uc5b4"},
es:{title:"Model Router \u2014 Admin",dashboard:"Panel",api_docs:"Docs API",json_api:"JSON API",overview:"Resumen",total_models:"Total modelos",current_preset:"Preajuste actual",models:"Modelos",routing_preset:"Preajuste de enrutamiento",semantic_cache:"Cach\u00e9 sem\u00e1ntica",learning:"Aprendizaje",th_model:"Modelo",th_provider:"Proveedor",th_mode:"Modo",th_cost_in:"Costo/1K Entrada",th_cost_out:"Costo/1K Salida",th_latency:"Latencia",th_action:"Acci\u00f3n",entries:"Entradas",hit_rate:"Tasa de acierto",total_hits:"Aciertos totales",total_queries:"Consultas totales",total_feedback:"Retroalimentaci\u00f3n total",positive:"Positivo",negative:"Negativo",samples_learned:"Muestras aprendidas",loading:"Cargando...",set_manual:"\u2192 manual",set_auto:"\u2192 auto",language:"Idioma"},
fr:{title:"Model Router \u2014 Admin",dashboard:"Tableau de bord",api_docs:"Docs API",json_api:"JSON API",overview:"Aper\u00e7u",total_models:"Total mod\u00e8les",current_preset:"Pr\u00e9r\u00e9glage actuel",models:"Mod\u00e8les",routing_preset:"Pr\u00e9r\u00e9glage routage",semantic_cache:"Cache s\u00e9mantique",learning:"Apprentissage",th_model:"Mod\u00e8le",th_provider:"Fournisseur",th_mode:"Mode",th_cost_in:"Co\u00fbt/1K Entr\u00e9e",th_cost_out:"Co\u00fbt/1K Sortie",th_latency:"Latence",th_action:"Action",entries:"Entr\u00e9es",hit_rate:"Taux de hit",total_hits:"Hits totaux",total_queries:"Requ\u00eates totales",total_feedback:"Retour total",positive:"Positif",negative:"N\u00e9gatif",samples_learned:"\u00c9chantillons appris",loading:"Chargement...",set_manual:"\u2192 manuel",set_auto:"\u2192 auto",language:"Langue"},
de:{title:"Model Router \u2014 Admin",dashboard:"Dashboard",api_docs:"API-Dokumentation",json_api:"JSON API",overview:"\u00dcbersicht",total_models:"Modelle gesamt",current_preset:"Aktuelle Voreinstellung",models:"Modelle",routing_preset:"Routing-Voreinstellung",semantic_cache:"Semantischer Cache",learning:"Lernen",th_model:"Modell",th_provider:"Anbieter",th_mode:"Modus",th_cost_in:"Kosten/1K Eingang",th_cost_out:"Kosten/1K Ausgang",th_latency:"Latenz",th_action:"Aktion",entries:"Eintr\u00e4ge",hit_rate:"Trefferquote",total_hits:"Gesamttreffer",total_queries:"Gesamtabfragen",total_feedback:"Gesamtfeedback",positive:"Positiv",negative:"Negativ",samples_learned:"Gelernte Samples",loading:"Laden...",set_manual:"\u2192 manuell",set_auto:"\u2192 auto",language:"Sprache"}
};
function t(k){const l=window._mrLang||'en';return(I18N[l]&&I18N[l][k])||I18N.en[k]||k}
function detectLang(){const p=new URLSearchParams(window.location.search);const u=p.get('lang');if(u&&I18N[u])return u;const s=localStorage.getItem('mr_lang');if(s&&I18N[s])return s;const n=(navigator.language||'en').split('-')[0].toLowerCase();if(I18N[n])return n;return'en'}
function setLang(l){if(!I18N[l])return;window._mrLang=l;localStorage.setItem('mr_lang',l);applyI18n();const s=document.getElementById('lang_selector');if(s)s.value=l}
function applyI18n(){document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.getAttribute('data-i18n');const v=t(k);if(el.tagName==='INPUT'||el.tagName==='TEXTAREA')el.placeholder=v;else el.textContent=v});document.title=t('title');document.documentElement.lang=window._mrLang||'en'}
window._mrLang=detectLang();
applyI18n();

function esc(s){if(!s)return"";var d=document.createElement("div");d.textContent=s;return d.innerHTML}
function toast(msg){var tt=document.getElementById("toast");tt.textContent=msg;tt.style.display="block";setTimeout(function(){tt.style.display="none"},2000)}
async function j(url){var r=await fetch(url);return r.json()}

async function loadModels(){
  var models=await j("/admin/models");
  document.getElementById("total_models").textContent=models.length;
  var autoC=0,manualC=0;
  models.forEach(function(m){if(m.selection_mode==="auto")autoC++;else manualC++});
  document.getElementById("auto_count").textContent=autoC;
  document.getElementById("manual_count").textContent=manualC;
  var tbody=document.getElementById("models_body");
  if(!models.length){tbody.innerHTML='<tr><td colspan=7 style=color:#888>'+t('loading')+'</td></tr>';return}
  tbody.innerHTML=models.map(function(m){
    var badge=m.selection_mode==="auto"?"badge-auto":"badge-manual";
    var btnText=m.selection_mode==="auto"?t('set_manual'):t('set_auto');
    var newMode=m.selection_mode==="auto"?"manual":"auto";
    return '<tr><td>'+esc(m.id)+'</td><td>'+esc(m.provider||"—")+'</td>'+
      '<td><span class="badge '+badge+'">'+esc(m.selection_mode)+'</span></td>'+
      '<td>$'+(m.cost_per_1k_input||0).toFixed(4)+'</td>'+
      '<td>$'+(m.cost_per_1k_output||0).toFixed(4)+'</td>'+
      '<td>'+esc(m.latency_tier||"—")+'</td>'+
      '<td><button class="btn btn-sm" data-toggle="'+esc(m.id)+'" data-mode="'+newMode+'">'+btnText+'</button></td></tr>';
  }).join("");
}

async function toggleMode(modelId,newMode){
  try{
    var r=await fetch("/admin/models/"+encodeURIComponent(modelId),{
      method:"PUT",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({selection_mode:newMode})
    });
    var d=await r.json();
    if(r.ok){toast(d.message||"Updated");loadModels()}
    else{toast("Error: "+(d.detail||"unknown"))}
  }catch(e){toast("Error: "+e.message)}
}

async function loadPreset(){
  var preset=await j("/admin/preset");
  document.getElementById("current_preset").textContent=preset.current;
  var card=document.getElementById("preset_card");
  var descs=preset.descriptions||{};
  card.innerHTML=preset.available.map(function(p){
    var cls=p===preset.current?"btn preset-btn active":"btn preset-btn";
    return '<button class="'+cls+'" data-preset="'+p+'">'+esc(p)+'</button>';
  }).join("")+'<div style="margin-top:8px;color:#888;font-size:0.85em" id="preset_desc"></div>';
  var desc=descs[preset.current]||"";
  document.getElementById("preset_desc").textContent=desc;
}

async function setPreset(name){
  try{
    var r=await fetch("/admin/preset/"+encodeURIComponent(name),{method:"PUT"});
    var d=await r.json();
    if(r.ok){toast("Preset: "+name);loadPreset()}
    else{toast("Error: "+(d.detail||"unknown"))}
  }catch(e){toast("Error: "+e.message)}
}

async function loadCache(){
  var cache=await j("/admin/cache");
  document.getElementById("cache_entries").textContent=cache.entries||0;
  document.getElementById("cache_hit_rate").textContent=((cache.hit_rate||0)*100).toFixed(1)+"%";
  document.getElementById("cache_hits").textContent=cache.hits||cache.total_hits||0;
  document.getElementById("cache_queries").textContent=(cache.hits||0)+(cache.misses||0);
}

async function loadLearning(){
  var learn=await j("/admin/learning");
  document.getElementById("total_feedback").textContent=learn.feedback?.total||0;
  document.getElementById("positive_fb").textContent=learn.feedback?.positive||0;
  document.getElementById("negative_fb").textContent=learn.feedback?.negative||0;
  document.getElementById("samples_learned").textContent=learn.learning?.total_samples||0;
}

// Event delegation for data-* buttons
document.addEventListener("click",function(e){
  var tgt=e.target;
  if(tgt.dataset.toggle){toggleMode(tgt.dataset.toggle,tgt.dataset.mode)}
  if(tgt.dataset.preset){setPreset(tgt.dataset.preset)}
});

loadModels();loadPreset();loadCache();loadLearning();
setInterval(loadModels,15000);setInterval(loadCache,10000);
document.getElementById('lang_selector').value = window._mrLang;
</script>
</body>
</html>
"""


@router.get("", include_in_schema=False)
async def admin_ui() -> HTMLResponse:
    """Admin management UI — served at /admin"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_ADMIN_UI_HTML)

"""
Admin API for runtime model configuration.

Allows agents and users to configure model selection modes
via HTTP API — no config file editing needed.

Multilingual: Supports EN, ZH, JA, KO, ES, FR, DE.

Endpoints:
    GET  /admin/models           — List all models with current config
    PUT  /admin/models/{id}      — Update a model's selection_mode
    POST /admin/models/batch     — Batch update multiple models
    GET  /admin/models/stats     — Routing statistics
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

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
# Endpoints
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

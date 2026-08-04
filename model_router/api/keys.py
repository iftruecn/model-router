"""
Virtual API Key management endpoints for Model Router v1.8.0.

Endpoints (all require the master key when auth is active):
    GET    /admin/keys          — List keys (masked) + usage stats
    POST   /admin/keys          — Create a key (raw key shown once)
    DELETE /admin/keys/{key_id} — Revoke a key
    PUT    /admin/keys/{key_id} — Enable/disable a key

Design notes:
- Lightweight single-instance auth, per FR-community-intel P0 #3
- Auth activates automatically when the first key is created
- Per-key usage = lightweight spend attribution (community ask)
- P1-13: key_manager uses threading.Lock (sync) — safe for async endpoints
  because file I/O is short and doesn't block the event loop significantly
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from model_router.core.auth import key_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/keys", tags=["admin-keys"])


class KeyCreateRequest(BaseModel):
    """Request body for creating a virtual API key."""
    label: str = Field(
        default="",
        max_length=64,
        description="Human-readable label, e.g. the agent/team name",
    )


class KeyUpdateRequest(BaseModel):
    """Request body for enabling/disabling a key."""
    enabled: bool = Field(..., description="true = active, false = revoked until re-enabled")


def _extract_bearer(request: Request) -> str:
    """Pull the raw key out of the Authorization header ('' if absent)."""
    auth = request.headers.get("Authorization", "")
    return auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""


def _require_master(request: Request) -> None:
    """
    Guard for key-management endpoints.

    - Auth off (no keys yet): open, so the first key can be created
    - Master key configured: only the master key may manage keys
    - No master key: any valid virtual key may manage keys
      (avoids lockout in zero-config single-instance setups)
    """
    if not key_manager.auth_enabled:
        return
    raw_key = _extract_bearer(request)
    if key_manager.master_key:
        if not key_manager.is_master(raw_key):
            raise HTTPException(
                status_code=403,
                detail="Key management requires the master key "
                       "(Authorization: Bearer $MODEL_ROUTER_MASTER_KEY)",
            )
    elif key_manager.verify(raw_key) is None:
        raise HTTPException(
            status_code=403,
            detail="Key management requires a valid API key",
        )


@router.get("")
async def list_keys(request: Request) -> dict:
    """List all virtual keys (masked) with per-key usage stats."""
    _require_master(request)
    keys = key_manager.list_keys()
    return {
        "auth_enabled": key_manager.auth_enabled,
        "count": len(keys),
        "keys": keys,
    }


@router.post("")
async def create_key(req: KeyCreateRequest, request: Request) -> dict:
    """
    Create a virtual API key.

    ⚠️ The raw key (``mr-sk-...``) is returned ONLY in this response.
    Store it immediately — only its hash is kept on disk.
    """
    _require_master(request)
    raw_key, record = key_manager.create_key(label=req.label)
    await key_manager.save()
    logger.info("API key created via API: %s", record["key_id"])
    return {
        "api_key": raw_key,  # shown once
        "key_id": record["key_id"],
        "label": record["label"],
        "note": "Save this key now — it cannot be retrieved later.",
    }


@router.delete("/{key_id}")
async def delete_key(key_id: str, request: Request) -> dict:
    """Revoke (delete) a virtual key by key_id."""
    _require_master(request)
    if not key_manager.delete_key(key_id):
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found")
    await key_manager.save()
    return {"key_id": key_id, "deleted": True}


@router.put("/{key_id}")
async def update_key(key_id: str, req: KeyUpdateRequest, request: Request) -> dict:
    """Enable or disable a virtual key without deleting it."""
    _require_master(request)
    if not key_manager.set_enabled(key_id, req.enabled):
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found")
    await key_manager.save()
    return {"key_id": key_id, "enabled": req.enabled}

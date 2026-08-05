"""
Virtual API Key management for Model Router v1.7.0.

Lightweight single-instance auth:
- Keys look like OpenAI keys: ``mr-sk-<32 url-safe chars>``
- Only SHA-256 hashes are persisted (``api_keys.json`` in data_dir)
- Auth activates automatically when the first key is created
  (or when ``MODEL_ROUTER_MASTER_KEY`` is set) — zero-config until then
- Per-key usage tracking (requests + estimated cost attribution)
- Master key (``MODEL_ROUTER_MASTER_KEY``) always passes and manages keys

No external dependencies. Multi-tenant attribution can build on this later.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Optional

from model_router.config.defaults import (
    AUTH_ENABLED_ENV,
    AUTH_KEY_PREFIX,
    AUTH_KEYS_FILE,
    AUTH_MASTER_KEY_ENV,
    AUTH_SCHEMA_VERSION,
    AUTH_TOKEN_BYTES,
    MEMORY_DEFAULT_DATA_DIR,
)

logger = logging.getLogger(__name__)


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw key — raw keys are never persisted."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _mask_key(raw_key: str) -> str:
    """Show only prefix + last 4 chars, e.g. ``mr-sk-ab12...wxyz``."""
    if len(raw_key) <= 12:
        return raw_key[:4] + "..."
    return f"{raw_key[:8]}...{raw_key[-4:]}"


class KeyManager:
    """
    In-memory virtual key store with atomic JSON persistence.

    Storage layout (``{data_dir}/api_keys.json``)::

        {
          "schema_version": 1,
          "keys": {
            "<sha256-hash>": {
              "key_id": "k_ab12cd34",
              "label": "hermes",
              "masked": "mr-sk-ab12...wxyz",
              "created_at": 1720000000.0,
              "enabled": true,
              "usage": {"requests": 0, "estimated_cost": 0.0, "last_used": null}
            }
          }
        }
    """

    def __init__(self, data_dir: str = MEMORY_DEFAULT_DATA_DIR) -> None:
        self._data_dir = data_dir
        self._keys: dict[str, dict] = {}  # sha256-hash -> record
        self._lock = threading.Lock()
        self._loaded = False

    # ----------------------------------------------------------
    # Properties
    # ----------------------------------------------------------

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @property
    def master_key(self) -> Optional[str]:
        """Master key from environment (never persisted)."""
        return os.environ.get(AUTH_MASTER_KEY_ENV) or None

    @property
    def auth_enabled(self) -> bool:
        """Auth is active once any virtual key exists (or master key set)."""
        if os.environ.get(AUTH_ENABLED_ENV, "").lower() in ("1", "true", "yes"):
            return False  # explicit kill switch (MODEL_ROUTER_AUTH_DISABLED=1)
        return bool(self._keys) or bool(self.master_key)

    # ----------------------------------------------------------
    # Key lifecycle
    # ----------------------------------------------------------

    def create_key(self, label: str = "") -> tuple[str, dict]:
        """
        Create a new virtual key.

        Returns:
            (raw_key, record) — raw_key is shown to the caller ONCE.
        """
        raw_key = AUTH_KEY_PREFIX + secrets.token_urlsafe(AUTH_TOKEN_BYTES)
        key_hash = _hash_key(raw_key)
        record = {
            "key_id": "k_" + secrets.token_hex(4),
            "label": label,
            "masked": _mask_key(raw_key),
            "created_at": time.time(),
            "enabled": True,
            "usage": {"requests": 0, "estimated_cost": 0.0, "last_used": None},
        }
        with self._lock:
            self._keys[key_hash] = record
        logger.info("API key created: %s (%s)", record["key_id"], label or "no label")
        return raw_key, record

    def list_keys(self) -> list[dict]:
        """List all key records (masked, never raw)."""
        with self._lock:
            return [dict(record) for record in self._keys.values()]

    def delete_key(self, key_id: str) -> bool:
        """Delete a key by its key_id. Returns True if removed."""
        with self._lock:
            for key_hash, record in list(self._keys.items()):
                if record["key_id"] == key_id:
                    del self._keys[key_hash]
                    logger.info("API key deleted: %s", key_id)
                    return True
        return False

    def set_enabled(self, key_id: str, enabled: bool) -> bool:
        """Enable/disable a key without deleting it."""
        with self._lock:
            for record in self._keys.values():
                if record["key_id"] == key_id:
                    record["enabled"] = enabled
                    logger.info("API key %s -> %s", key_id, "enabled" if enabled else "disabled")
                    return True
        return False

    # ----------------------------------------------------------
    # Verification
    # ----------------------------------------------------------

    def verify(self, raw_key: str) -> Optional[dict]:
        """
        Verify a raw key (constant-time hash comparison).

        Returns:
            The key record if valid and enabled, None otherwise.
        """
        if not raw_key:
            return None
        # Master key always passes (admin operations, single-instance)
        master = self.master_key
        if master and hmac.compare_digest(raw_key, master):
            return {"key_id": "__master__", "label": "master", "usage": None}
        key_hash = _hash_key(raw_key)
        with self._lock:
            record = self._keys.get(key_hash)
            if record and record["enabled"]:
                return record
        return None

    def is_master(self, raw_key: str) -> bool:
        """Check whether raw_key is the master key."""
        master = self.master_key
        return bool(master and raw_key and hmac.compare_digest(raw_key, master))

    def record_usage(self, key_id: str, estimated_cost: float = 0.0) -> None:
        """Attribute a request (and optional cost) to a key."""
        with self._lock:
            for record in self._keys.values():
                if record["key_id"] == key_id:
                    usage = record["usage"]
                    usage["requests"] += 1
                    usage["estimated_cost"] += estimated_cost
                    usage["last_used"] = time.time()
                    break

    # ----------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------

    async def load(self) -> None:
        """Load keys from disk (idempotent)."""
        import asyncio
        path = os.path.join(self._data_dir, AUTH_KEYS_FILE)
        if not os.path.exists(path):
            self._loaded = True
            return
        try:
            data = await asyncio.to_thread(self._load_keys_sync, path)
            with self._lock:
                self._keys = data
            logger.info("Loaded %d API keys from %s", len(self._keys), path)
        except Exception as exc:
            logger.error("Failed to load API keys: %s", exc)
        self._loaded = True

    def _load_keys_sync(self, path: str) -> dict:
        """Synchronous key loading (called via to_thread)."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("keys", {})

    async def save(self) -> None:
        """Atomic write (tmp + os.replace)."""
        import asyncio
        os.makedirs(self._data_dir, exist_ok=True)
        path = os.path.join(self._data_dir, AUTH_KEYS_FILE)
        tmp = path + ".tmp"
        with self._lock:
            data = {"schema_version": AUTH_SCHEMA_VERSION, "keys": dict(self._keys)}
        try:
            await asyncio.to_thread(self._save_keys_sync, tmp, path, data)
        except Exception as exc:
            logger.error("Failed to persist API keys: %s", exc)

    @staticmethod
    def _save_keys_sync(tmp: str, path: str, data: dict) -> None:
        """Synchronous key saving (called via to_thread)."""
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


# Global singleton (mirrors memory_store / learner patterns)
key_manager = KeyManager()

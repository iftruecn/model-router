"""
Security utilities for Model Router v1.7.0.

API key masking (desensitization) and environment key sync.
"""

import hashlib
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def mask_key(key: str, visible_prefix: int = 3, visible_suffix: int = 4) -> str:
    """
    Mask an API key for safe display.

    Examples:
        mask_key("sk-0fa2f31236b7405daa803429c36498ff") → "sk-****98ff"
        mask_key("short")                                → "*****"
        mask_key("")                                     → "********"
    """
    if not key:
        return "********"
    if len(key) <= visible_prefix + visible_suffix:
        return "*" * len(key)
    return (
        key[:visible_prefix]
        + "****"
        + key[-visible_suffix:]
    )


def mask_config_keys(models_config: dict) -> dict:
    """
    Return a copy of models_config with all api_key fields masked.

    Safe for logging, API responses, and dashboard display.
    """
    masked = {}
    for key, cfg in models_config.items():
        masked_cfg = dict(cfg)
        if "api_key" in masked_cfg:
            masked_cfg["api_key"] = mask_key(masked_cfg["api_key"])
        masked[key] = masked_cfg
    return masked


class EnvKeySync:
    """
    Monitor environment variable API keys for changes.

    On startup, records the hash of each known env var.
    Periodic check (or manual trigger) detects changes and
    triggers config reload.

    Usage:
        sync = EnvKeySync()
        sync.snapshot()           # record current state
        changed = sync.check()    # returns list of changed env vars
    """

    def __init__(self):
        from model_router.config.auto_config import KNOWN_KEYS
        self._known_keys = KNOWN_KEYS
        self._hashes: dict[str, str] = {}

    def _key_hash(self, value: str) -> str:
        """SHA-256 hash of a key value (first 16 chars of hex digest)."""
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def snapshot(self) -> None:
        """Record current env var state."""
        self._hashes = {}
        for env_var in self._known_keys:
            value = os.environ.get(env_var, "").strip()
            if value:
                self._hashes[env_var] = self._key_hash(value)
        # P2-17 fix: downgrade to DEBUG to avoid partial key exposure
        logger.debug(
            "EnvKeySync snapshot: %d keys tracked (%s)",
            len(self._hashes),
            ", ".join(
                f"{v}={mask_key(os.environ.get(v, ''))}"
                for v in self._hashes
            ),
        )
        logger.info("EnvKeySync snapshot: %d keys tracked", len(self._hashes))

    def check(self) -> list[str]:
        """
        Check for changed env vars.

        Returns list of env var names that have changed since last snapshot.
        Empty list means no changes.
        """
        changed: list[str] = []
        for env_var in self._known_keys:
            value = os.environ.get(env_var, "").strip()
            if not value:
                # Key was removed
                if env_var in self._hashes:
                    changed.append(env_var)
                    logger.warning(
                        "API key removed: %s", env_var,
                    )
                continue

            current_hash = self._key_hash(value)
            old_hash = self._hashes.get(env_var)
            if old_hash and old_hash != current_hash:
                changed.append(env_var)
                logger.info(
                    "API key changed: %s (old=%s, new=%s)",
                    env_var,
                    mask_key(os.environ.get(env_var, "")[:8] + "old"),
                    mask_key(value),
                )
            elif old_hash is None:
                # New key appeared
                changed.append(env_var)
                logger.info(
                    "API key added: %s (%s)",
                    env_var, mask_key(value),
                )

        return changed

    def update_snapshot(self) -> None:
        """Update snapshot after handling changes."""
        self.snapshot()


# Global instance
env_key_sync = EnvKeySync()

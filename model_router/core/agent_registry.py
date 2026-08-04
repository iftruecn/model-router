"""
Agent Registry for Model Router v1.5.0.

Manages multi-agent registration:
- Each agent gets a unique Router API Key (mr-sk-<agent>-<random>)
- Key -> Agent mapping for request routing
- Per-agent model lists (each agent sees only its own models)
- Per-agent usage statistics
"""

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from model_router.config.defaults import MEMORY_DEFAULT_DATA_DIR

logger = logging.getLogger(__name__)

# Registry file in data_dir
AGENT_REGISTRY_FILE = "agent_registry.json"


class AgentRegistry:
    """
    Multi-agent registry with JSON persistence.

    Storage layout ({data_dir}/agent_registry.json)::

        {
          "schema_version": 1,
          "agents": {
            "hermes": {
              "agent_type": "hermes",
              "config_path": "E:\\AI\\HermesData\\config.yaml",
              "router_key_hash": "abc123...",
              "router_key_masked": "mr-sk-hermes-...xyz",
              "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
              "installed_at": 1720000000.0,
              "usage": {"requests": 0, "fallbacks": 0}
            },
            "openclaw": { ... }
          }
        }
    """

    def __init__(self, data_dir: str = MEMORY_DEFAULT_DATA_DIR):
        self._data_dir = data_dir
        self._agents: dict = {}  # agent_type -> agent record
        self._key_hash_map: dict = {}  # key_hash -> agent_type
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @property
    def agents(self) -> dict:
        """Return all registered agents."""
        self._ensure_loaded()
        return dict(self._agents)

    def _ensure_loaded(self):
        if not self._loaded:
            self._load()

    def _registry_path(self) -> Path:
        return Path(self._data_dir) / AGENT_REGISTRY_FILE

    def _load(self):
        """Load registry from disk."""
        path = self._registry_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._agents = data.get("agents", {})
                # Rebuild key hash map
                self._key_hash_map = {}
                for agent_type, record in self._agents.items():
                    kh = record.get("router_key_hash")
                    if kh:
                        self._key_hash_map[kh] = agent_type
                logger.info("Agent registry loaded: %d agent(s)", len(self._agents))
            except Exception as e:
                logger.warning("Failed to load agent registry: %s", e)
                self._agents = {}
        self._loaded = True

    def _save(self):
        """Persist registry to disk."""
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "agents": self._agents,
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def generate_agent_key(self, agent_type: str) -> str:
        """Generate a unique Router API key for an agent."""
        # Format: mr-sk-<agent>-<random>
        random_part = secrets.token_urlsafe(16)
        raw_key = "mr-sk-{}-{}".format(agent_type, random_part)
        return raw_key

    def register_agent(
        self,
        agent_type: str,
        config_path: str,
        router_key_raw: str,
        models: list,
    ):
        """Register or update an agent."""
        key_hash = hashlib.sha256(router_key_raw.encode("utf-8")).hexdigest()
        masked = _mask_key(router_key_raw)

        with self._lock:
            existing = self._agents.get(agent_type, {})
            usage = existing.get("usage", {"requests": 0, "fallbacks": 0})

            self._agents[agent_type] = {
                "agent_type": agent_type,
                "config_path": config_path,
                "router_key_hash": key_hash,
                "router_key_masked": masked,
                "models": models,
                "installed_at": existing.get("installed_at", time.time()),
                "updated_at": time.time(),
                "usage": usage,
            }
            self._key_hash_map[key_hash] = agent_type
            self._save()

        logger.info(
            "Agent registered: %s (key=%s, models=%d)",
            agent_type, masked, len(models),
        )

    def lookup_agent_by_key(self, key_hash: str) -> Optional[str]:
        """Find which agent a request key belongs to."""
        self._ensure_loaded()
        return self._key_hash_map.get(key_hash)

    def get_agent_models(self, agent_type: str) -> list:
        """Get the model list for a specific agent."""
        self._ensure_loaded()
        record = self._agents.get(agent_type, {})
        return record.get("models", [])

    def get_agent_stats(self, agent_type: str = None) -> dict:
        """Get usage stats for one or all agents."""
        self._ensure_loaded()
        if agent_type:
            record = self._agents.get(agent_type, {})
            return {
                "agent_type": agent_type,
                "masked_key": record.get("router_key_masked", ""),
                "models": record.get("models", []),
                "usage": record.get("usage", {}),
            }
        # All agents
        result = {}
        for at, record in self._agents.items():
            result[at] = {
                "masked_key": record.get("router_key_masked", ""),
                "models": record.get("models", []),
                "usage": record.get("usage", {}),
            }
        return result

    def record_request(self, agent_type: str):
        """Record a request from an agent."""
        with self._lock:
            if agent_type in self._agents:
                self._agents[agent_type]["usage"]["requests"] = (
                    self._agents[agent_type]["usage"].get("requests", 0) + 1
                )
                self._save()

    def record_fallback(self, agent_type: str):
        """Record a fallback event for an agent."""
        with self._lock:
            if agent_type in self._agents:
                self._agents[agent_type]["usage"]["fallbacks"] = (
                    self._agents[agent_type]["usage"].get("fallbacks", 0) + 1
                )
                self._save()

    def is_installed(self, agent_type: str) -> bool:
        """Check if an agent has been installed (registered)."""
        self._ensure_loaded()
        return agent_type in self._agents

    def unregister_agent(self, agent_type: str):
        """Remove an agent from the registry."""
        with self._lock:
            record = self._agents.pop(agent_type, None)
            if record:
                kh = record.get("router_key_hash")
                if kh and kh in self._key_hash_map:
                    del self._key_hash_map[kh]
                self._save()
                logger.info("Agent unregistered: %s", agent_type)


def _mask_key(raw_key):
    """Show only prefix + last 4 chars."""
    if len(raw_key) <= 12:
        return raw_key[:4] + "..."
    return "{}...{}".format(raw_key[:8], raw_key[-4:])


# Global singleton
_registry = None
_registry_lock = threading.Lock()


def get_agent_registry(data_dir: str = MEMORY_DEFAULT_DATA_DIR) -> AgentRegistry:
    """Get or create the global agent registry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = AgentRegistry(data_dir)
    return _registry

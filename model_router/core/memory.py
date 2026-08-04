"""
Persistent memory store for Model Router v1.2.0.

Stores routing learning statistics (Gaussian TS parameters, EWMA scores,
cost accounting) and a ring-buffered request log for feedback attribution
and offline evaluation.

Design principles (FR-持久记忆与自学习):
- Fixed-size aggregate stats: memory does NOT grow with request volume
- Ring buffer for request log: bounded, oldest entries overwritten
- Atomic writes: tmp file + os.replace, never corrupt on crash
- Versioned schema: meta.json carries schema_version for future migration
- Namespace-ready: data_dir/instances/{agent_id}/ prepared for multi-agent

All interfaces are async to leave room for a future SQLite backend
without changing call sites (Hermes review 2026-08-03).
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from model_router.config.defaults import (
    MEMORY_DEFAULT_AGENT,
    MEMORY_MAX_REQUEST_LOG,
    MEMORY_SAVE_INTERVAL,
    MEMORY_SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    JSON-file backed persistent memory with atomic writes.

    Layout under data_dir:
        meta.json                         schema version + migration record
        global/capability.json            global-layer stats (future)
        instances/{agent_id}/routing_stats.json   per-agent learning stats
        instances/{agent_id}/request_log.jsonl    ring-buffered request log
    """

    def __init__(
        self,
        data_dir: str = "data",
        agent_id: str = MEMORY_DEFAULT_AGENT,
        max_request_log: int = MEMORY_MAX_REQUEST_LOG,
    ):
        self._data_dir = data_dir
        self._agent_id = agent_id
        self._max_request_log = max_request_log
        self._lock = asyncio.Lock()
        self._dirty = False
        self._loaded = False

        # In-memory state (aggregates: fixed size, independent of traffic)
        self._stats: dict[str, Any] = {
            "gaussian": {},      # "{task}|{model}" -> {mu, m2, n, ewma}
            "cost": {
                "total_estimated_cost": 0.0,
                "baseline_estimated_cost": 0.0,
                "total_requests": 0,
            },
        }
        # Ring buffer: grows only up to max_request_log entries
        self._request_log: list[dict] = []

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def _instance_dir(self) -> str:
        return os.path.join(self._data_dir, "instances", self._agent_id)

    def _stats_path(self) -> str:
        return os.path.join(self._instance_dir(), "routing_stats.json")

    def _log_path(self) -> str:
        return os.path.join(self._instance_dir(), "request_log.jsonl")

    def _meta_path(self) -> str:
        return os.path.join(self._data_dir, "meta.json")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load persisted state from disk (idempotent)."""
        if self._loaded:
            return
        async with self._lock:
            await asyncio.to_thread(self._load_sync)
            self._loaded = True
            logger.info(
                "MemoryStore loaded: agent=%s, stats_keys=%d, log_entries=%d",
                self._agent_id, len(self._stats.get("gaussian", {})), len(self._request_log),
            )

    def _load_sync(self) -> None:
        # meta.json: schema version check / migration hook
        meta = self._read_json(self._meta_path())
        stored_version = meta.get("schema_version", 0)
        if stored_version != MEMORY_SCHEMA_VERSION:
            logger.info(
                "Schema migration: %s -> %s", stored_version, MEMORY_SCHEMA_VERSION
            )
            self._write_json(self._meta_path(), {
                "schema_version": MEMORY_SCHEMA_VERSION,
                "created": meta.get("created", time.time()),
                "migrated": time.time(),
            })

        # routing stats
        stats = self._read_json(self._stats_path())
        if stats:
            self._stats["gaussian"] = stats.get("gaussian", {})
            cost = stats.get("cost", {})
            self._stats["cost"].update({
                "total_estimated_cost": cost.get("total_estimated_cost", 0.0),
                "baseline_estimated_cost": cost.get("baseline_estimated_cost", 0.0),
                "total_requests": cost.get("total_requests", 0),
            })

        # request log (ring buffer tail)
        if os.path.exists(self._log_path()):
            entries: list[dict] = []
            try:
                with open(self._log_path(), "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                self._request_log = entries[-self._max_request_log:]
            except OSError as exc:
                logger.warning("Failed to read request log: %s", exc)

    async def save(self) -> None:
        """Persist current state atomically (tmp + os.replace)."""
        async with self._lock:
            await asyncio.to_thread(self._save_sync)
            self._dirty = False

    def _save_sync(self) -> None:
        os.makedirs(self._instance_dir(), exist_ok=True)
        os.makedirs(os.path.dirname(self._meta_path()), exist_ok=True)

        if not os.path.exists(self._meta_path()):
            self._write_json(self._meta_path(), {
                "schema_version": MEMORY_SCHEMA_VERSION,
                "created": time.time(),
            })

        self._write_json(self._stats_path(), self._stats)

        with open(self._log_path(), "w", encoding="utf-8") as fh:
            for entry in self._request_log:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    async def maybe_save(self, force: bool = False) -> None:
        """Save only when dirty and due (called after each update)."""
        if not self._dirty:
            return
        cost = self._stats["cost"]
        # P1-3 fix: skip when total_requests==0 (0%N==0 triggers unwanted first-write)
        if force or (cost["total_requests"] > 0 and cost["total_requests"] % MEMORY_SAVE_INTERVAL == 0):
            await self.save()

    # ------------------------------------------------------------------
    # Learning stats (fixed-size aggregates)
    # ------------------------------------------------------------------

    def get_model_stats(self, task: str, model: str) -> Optional[dict]:
        """Get Gaussian stats for a (task, model) pair, or None."""
        return self._stats["gaussian"].get(f"{task}|{model}")

    def update_model_stats(self, task: str, model: str, stats: dict) -> None:
        """Upsert Gaussian stats for a (task, model) pair."""
        self._stats["gaussian"][f"{task}|{model}"] = stats
        self._dirty = True

    def all_model_stats(self) -> dict:
        """Return a copy of all (task|model) stats."""
        return dict(self._stats["gaussian"])

    # ------------------------------------------------------------------
    # Cost accounting
    # ------------------------------------------------------------------

    def add_cost(
        self,
        estimated_cost: float,
        baseline_cost: float,
    ) -> None:
        """
        Record cost of one routed request.

        Args:
            estimated_cost: cost of the model actually used
            baseline_cost: cost of the strongest (most expensive) candidate,
                           used to quantify savings
        """
        cost = self._stats["cost"]
        cost["total_estimated_cost"] += max(0.0, estimated_cost)
        cost["baseline_estimated_cost"] += max(0.0, baseline_cost)
        cost["total_requests"] += 1
        self._dirty = True

    def get_cost_stats(self) -> dict:
        cost = self._stats["cost"]
        saved = cost["baseline_estimated_cost"] - cost["total_estimated_cost"]
        pct = (
            saved / cost["baseline_estimated_cost"] * 100.0
            if cost["baseline_estimated_cost"] > 0
            else 0.0
        )
        return {
            "total_requests": cost["total_requests"],
            "total_estimated_cost": round(cost["total_estimated_cost"], 6),
            "baseline_estimated_cost": round(cost["baseline_estimated_cost"], 6),
            "estimated_savings": round(saved, 6),
            "savings_percent": round(pct, 1),
        }

    # ------------------------------------------------------------------
    # Request log (ring buffer, bounded)
    # ------------------------------------------------------------------

    def append_request_log(self, entry: dict) -> None:
        """Append one routing-chain record; drops oldest when full."""
        self._request_log.append(entry)
        overflow = len(self._request_log) - self._max_request_log
        if overflow > 0:
            del self._request_log[:overflow]
        self._dirty = True

    def get_request(self, request_id: str) -> Optional[dict]:
        """Find a logged request by id (for feedback attribution)."""
        for entry in reversed(self._request_log):
            if entry.get("request_id") == request_id:
                return entry
        return None

    def recent_requests(self, limit: int = 20) -> list[dict]:
        return self._request_log[-limit:]

    # ------------------------------------------------------------------
    # IO helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return {}

    @staticmethod
    def _write_json(path: str, data: dict) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)  # atomic on Windows & POSIX

    def reset(self) -> None:
        """Clear all in-memory state (does not delete files)."""
        self._stats["gaussian"] = {}
        self._stats["cost"] = {
            "total_estimated_cost": 0.0,
            "baseline_estimated_cost": 0.0,
            "total_requests": 0,
        }
        self._request_log = []
        self._dirty = True


# Global singleton (data_dir overridable at startup)
memory_store = MemoryStore()

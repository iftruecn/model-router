"""
Agent capability adapter layer (v1.2.0) with hot sensing.

Agents (Hermes / OpenClaw / ...) can declare what they can lend us:
vector DB, persistent memory, knowledge base. The Router only READS
from these, never writes, and falls back silently when unavailable.

Implemented:
  - declaration parsing + registry + status (v1.0.4)
  - capability fingerprint + in-band hot sensing (X-Agent-Capabilities)
  - declaration persistence (capabilities.json, api_keys.json style)
Concrete borrowing adapters (vector / memory / knowledge) arrive in
v1.1+ behind the same CapabilityAdapter interface.

Hard constraints (FR §2.4):
  1. read-only   — adapters never write to agent storage
  2. no persist  — borrowed queries/results are never persisted
  3. kill switch — no declarations => everything off (zero impact)
  4. isolation   — borrow failures never block the routing path
"""

import base64
import hashlib
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field

from model_router.config.defaults import (
    CAPABILITIES_FILE,
    CAPABILITIES_TIMEOUT_MS,
    CAPABILITIES_USE_FOR,
    CAPABILITY_EVENTS_MAX,
)

logger = logging.getLogger(__name__)

KNOWN_CAPABILITIES = ("vector_db", "memory", "knowledge_base")


def canonical_fingerprint(capabilities: dict) -> str:
    """sha1[:16] over canonical (sorted, compact) JSON of the declaration."""
    payload = json.dumps(
        capabilities or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class CapabilityDeclaration:
    """How to access one borrowed capability (access info only, no content)."""
    name: str
    type: str = ""
    endpoint: str = ""
    path: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"name": self.name, "type": self.type}
        if self.endpoint:
            d["endpoint"] = self.endpoint
        if self.path:
            d["path"] = self.path
        if self.meta:
            d["meta"] = self.meta
        return d


class CapabilityAdapter:
    """
    Abstract adapter interface. Concrete implementations (VectorAdapter,
    MemoryAdapter, KnowledgeAdapter) land in v1.1+; all must stay
    read-only and respect ``timeout_ms`` from the registry.
    """

    name = ""

    def __init__(self, declaration: CapabilityDeclaration):
        self.declaration = declaration

    def available(self) -> bool:
        """Whether this adapter can actually serve queries right now."""
        return False  # placeholder until real adapters land


class CapabilityRegistry:
    """Parse declarations, sense changes in-band, and persist state."""

    def __init__(
        self,
        use_for: dict = None,
        timeout_ms: int = CAPABILITIES_TIMEOUT_MS,
        data_dir: str = "",
    ):
        self._declarations: dict[str, CapabilityDeclaration] = {}
        self._specs: dict[str, dict] = {}       # raw specs (for fingerprint)
        self.use_for = dict(use_for or CAPABILITIES_USE_FOR)
        self.timeout_ms = timeout_ms
        self._data_dir = data_dir
        self.agent_id: str = ""
        self.fingerprint: str = ""
        self.updated_at: float = 0.0
        # Audit ring: recent capability-change events (FR §3)
        self._events: deque = deque(maxlen=CAPABILITY_EVENTS_MAX)

    # ------------------------------------------------------------------
    # Persistence (capabilities.json, same atomic pattern as api_keys)
    # ------------------------------------------------------------------

    @property
    def data_dir(self) -> str:
        return self._data_dir

    def _state_path(self) -> str:
        return os.path.join(self._data_dir, CAPABILITIES_FILE)

    def _events_path(self) -> str:
        return os.path.join(
            self._data_dir, "instances", self.agent_id or "default",
            "capability_events.jsonl",
        )

    def bind(self, data_dir: str) -> None:
        """Attach a data dir and load persisted state (app lifespan)."""
        self._data_dir = data_dir
        self._load()

    def _load(self) -> None:
        if not self._data_dir:
            return
        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read capabilities state: %s", exc)
            return
        self.agent_id = state.get("agent_id", "")
        self.declare(
            state.get("capabilities", {}),
            agent_id=self.agent_id,
            source="startup",
            persist=False,
        )

    def save(self) -> None:
        """Persist current declaration atomically (tmp + os.replace)."""
        if not self._data_dir:
            return
        path = self._state_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        state = {
            "agent_id": self.agent_id,
            "capabilities": self._specs,
            "fingerprint": self.fingerprint,
            "updated_at": self.updated_at,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ------------------------------------------------------------------
    # Declaration management
    # ------------------------------------------------------------------

    def declare(
        self,
        capabilities: dict,
        agent_id: str = "",
        source: str = "admin",
        persist: bool = True,
    ) -> list[str]:
        """
        Replace current declarations with the given map.

        Args:
            capabilities: {name: {"type": ..., "endpoint": ..., ...}};
                          entries without a "type" are skipped with a warning.
            agent_id: owning agent (kept for audit/status)
            source: where the declaration came from (admin/inline/startup)
            persist: write capabilities.json (startup load passes False)

        Returns:
            Sorted list of accepted capability names.
        """
        diff = self.diff(capabilities)
        old_specs = dict(self._specs)

        self._declarations.clear()
        self._specs.clear()
        declared = []
        for name, spec in (capabilities or {}).items():
            if not isinstance(spec, dict) or not spec.get("type"):
                logger.warning("Skipping invalid capability declaration: %s", name)
                continue
            self._declarations[name] = CapabilityDeclaration(
                name=name,
                type=str(spec["type"]),
                endpoint=str(spec.get("endpoint", "")),
                path=str(spec.get("path", "")),
                meta={
                    k: v for k, v in spec.items()
                    if k not in ("type", "endpoint", "path")
                },
            )
            self._specs[name] = dict(spec)
            declared.append(name)

        if agent_id:
            self.agent_id = agent_id
        self.fingerprint = canonical_fingerprint(self._specs)
        self.updated_at = time.time()

        # Audit event (skip no-op startup loads of identical state)
        if diff["added"] or diff["upgraded"] or diff["removed"] or source != "startup":
            self._record_event(source, diff, old_specs)
        if persist and self._data_dir:
            self.save()
        return sorted(declared)

    def diff(self, new_capabilities: dict) -> dict:
        """Compare current declarations against a candidate map (FR §2.4)."""
        added, upgraded, removed = [], [], []
        new_specs = {
            k: v for k, v in (new_capabilities or {}).items()
            if isinstance(v, dict) and v.get("type")
        }
        for name, spec in new_specs.items():
            old = self._specs.get(name)
            if old is None:
                added.append(name)
            elif old != spec:
                upgraded.append(name)
        for name in self._specs:
            if name not in new_specs:
                removed.append(name)
        return {"added": added, "upgraded": upgraded, "removed": removed}

    def _record_event(self, source: str, diff: dict, old_specs: dict) -> None:
        event = {
            "ts": time.time(),
            "source": source,
            "agent_id": self.agent_id,
            "diff": diff,
            "fingerprint": self.fingerprint,
        }
        self._events.append(event)
        if self._data_dir:
            try:
                path = self._events_path()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError as exc:
                logger.warning("Failed to append capability event: %s", exc)

    # ------------------------------------------------------------------
    # In-band hot sensing (FR-热感知 §2.2)
    # ------------------------------------------------------------------

    def observe(
        self,
        agent_id: str,
        fingerprint_header: str,
        full_b64: str = "",
    ) -> dict:
        """
        Piggyback sensing: compare the fingerprint carried on a request
        against the known one; hot-refresh when the full declaration
        rides along. Never raises — sensing failures are silently ignored.
        """
        fingerprint_header = (fingerprint_header or "").strip()
        if not fingerprint_header:
            return {"action": "ignored"}
        if fingerprint_header == self.fingerprint and (
            not self.agent_id or self.agent_id == agent_id
        ):
            return {"action": "unchanged"}
        if not full_b64:
            return {"action": "needs_full"}
        try:
            decoded = json.loads(base64.b64decode(full_b64).decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("declaration must be a JSON object")
        except Exception as exc:
            logger.warning("Bad X-Agent-Capabilities-Full payload: %s", exc)
            return {"action": "invalid_payload"}
        diff = self.diff(decoded)
        self.declare(decoded, agent_id=agent_id, source="inline")
        return {"action": "hot_updated", "diff": diff}

    # ------------------------------------------------------------------
    # Lookup / status
    # ------------------------------------------------------------------

    def get(self, name: str):
        """Return the declaration for one capability, or None."""
        return self._declarations.get(name)

    def list(self) -> list[str]:
        return sorted(self._declarations)

    @property
    def enabled(self) -> bool:
        """No declarations => everything off (FR §2.3 zero-impact default)."""
        return bool(self._declarations)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "agent_id": self.agent_id,
            "fingerprint": self.fingerprint,
            "updated_at": self.updated_at,
            "note": "static declaration only; borrowing hooks arrive in v1.1+",
            "declared": {
                name: d.to_dict() for name, d in self._declarations.items()
            },
            "use_for": dict(self.use_for),
            "timeout_ms": self.timeout_ms,
            "recent_events": list(self._events)[-5:],
        }


# Global singleton
capability_registry = CapabilityRegistry()

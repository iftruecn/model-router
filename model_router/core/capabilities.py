"""
Agent capability adapter layer (v1.0.4 — static declaration phase).

Agents (Hermes / OpenClaw / ...) can declare what they can lend us:
vector DB, persistent memory, knowledge base. The Router only READS
from these, never writes, and falls back silently when unavailable.

This phase implements: declaration parsing + registry + status.
Concrete borrowing adapters (vector / memory / knowledge) arrive in
v1.1+ behind the same CapabilityAdapter interface.

Hard constraints (FR §2.4):
  1. read-only   — adapters never write to agent storage
  2. no persist  — borrowed queries/results are never persisted
  3. kill switch — no declarations => everything off (zero impact)
  4. isolation   — borrow failures never block the routing path
"""

import logging
from dataclasses import dataclass, field

from model_router.config.defaults import (
    CAPABILITIES_TIMEOUT_MS,
    CAPABILITIES_USE_FOR,
)

logger = logging.getLogger(__name__)

KNOWN_CAPABILITIES = ("vector_db", "memory", "knowledge_base")


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
    """Parse capability declarations and hand them to adapters."""

    def __init__(
        self,
        use_for: dict = None,
        timeout_ms: int = CAPABILITIES_TIMEOUT_MS,
    ):
        self._declarations: dict[str, CapabilityDeclaration] = {}
        self.use_for = dict(use_for or CAPABILITIES_USE_FOR)
        self.timeout_ms = timeout_ms

    # ------------------------------------------------------------------
    # Declaration management
    # ------------------------------------------------------------------

    def declare(self, capabilities: dict) -> list[str]:
        """
        Replace current declarations with the given map.

        Args:
            capabilities: {name: {"type": ..., "endpoint": ..., ...}};
                          entries without a "type" are skipped with a warning.

        Returns:
            Sorted list of accepted capability names.
        """
        self._declarations.clear()
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
            declared.append(name)
        return sorted(declared)

    def get(self, name: str):
        """Return the declaration for one capability, or None."""
        return self._declarations.get(name)

    def list(self) -> list[str]:
        return sorted(self._declarations)

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """No declarations => everything off (FR §2.3 zero-impact default)."""
        return bool(self._declarations)

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "note": "static declaration only; borrowing hooks arrive in v1.1+",
            "declared": {
                name: d.to_dict() for name, d in self._declarations.items()
            },
            "use_for": dict(self.use_for),
            "timeout_ms": self.timeout_ms,
        }


# Global singleton
capability_registry = CapabilityRegistry()

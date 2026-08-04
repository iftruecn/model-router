"""
Application runtime context (v1.8.0).

Collects all runtime singletons into one container so that:
- Hot reload (F8) can swap the context without touching module globals
- Endpoints access dependencies via request.app.state.ctx
- Backward compatible: module globals still exist as fallbacks
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class AppContext:
    """
    Container for all Model Router runtime singletons.

    Stored on app.state.ctx by the lifespan manager.
    Endpoints and services access dependencies through this container
    instead of importing module-level globals.
    """
    # Core services
    router: Any = None          # SmartRouter
    learner: Any = None         # Learner
    guard: Any = None           # DiversityGuard
    memory: Any = None          # MemoryStore

    # Provider layer
    registry: Any = None        # ModelRegistry
    pool: Any = None            # ConnectionPool

    # Auth & capabilities
    keys: Any = None            # KeyManager
    capabilities: Any = None    # CapabilityRegistry
    agent_registry: Any = None  # AgentRegistry (v1.8.0 P0-1)

    # Config (mutable for hot reload)
    models_config: dict = None       # type: ignore[assignment]
    fallback_chain_config: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.models_config is None:
            self.models_config = {}
        if self.fallback_chain_config is None:
            self.fallback_chain_config = {}

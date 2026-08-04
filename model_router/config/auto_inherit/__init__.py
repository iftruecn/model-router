"""
Agent config auto-inheritance for Model Router v1.4.0.

Automatically discovers and inherits API keys and model
configurations from known Agent frameworks (Hermes, Claude Code, etc.)

Priority: Router config.yaml > env vars > Agent config > defaults
"""

from model_router.config.auto_inherit.detector import (
    discover_agent_config,
    parse_agent_providers,
    build_models_from_agent,
)

__all__ = [
    "discover_agent_config",
    "parse_agent_providers",
    "build_models_from_agent",
]

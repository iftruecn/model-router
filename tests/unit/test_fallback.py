"""
Unit tests for FallbackManager.

Tests fallback chain construction, limits, and automatic chain building.
"""

import pytest
from model_router.core.fallback import FallbackManager


@pytest.fixture
def manager():
    """Create a FallbackManager with limit of 3 attempts."""
    return FallbackManager(max_attempts=3)


@pytest.fixture
def models_config():
    """Sample models configuration."""
    return {
        "gpt-4o": {"tier": "pro", "name": "GPT-4o"},
        "gpt-4o-mini": {"tier": "flash", "name": "GPT-4o Mini"},
        "claude-sonnet": {"tier": "pro", "name": "Claude Sonnet"},
        "deepseek-v4": {"tier": "pro", "name": "DeepSeek V4"},
    }


def test_max_attempts_property(manager: FallbackManager):
    """Test max_attempts property."""
    assert manager.max_attempts == 3


def test_build_chain_with_explicit_config(manager: FallbackManager, models_config: dict):
    """Test building chain with explicit fallback config."""
    explicit_config = {
        "gpt-4o": ["claude-sonnet", "deepseek-v4"],
    }
    chain = manager.build_chain("gpt-4o", explicit_config, models_config)
    # Should include primary + 2 fallbacks (max_attempts=3)
    assert chain == ["gpt-4o", "claude-sonnet", "deepseek-v4"]


def test_build_chain_respects_limit(manager: FallbackManager, models_config: dict):
    """Test that chain is limited to max_attempts."""
    explicit_config = {
        "gpt-4o": ["claude-sonnet", "deepseek-v4", "gpt-4o-mini"],
    }
    chain = manager.build_chain("gpt-4o", explicit_config, models_config)
    # Should be limited to 3 total (primary + 2 fallbacks)
    assert len(chain) == 3
    assert chain == ["gpt-4o", "claude-sonnet", "deepseek-v4"]


def test_build_chain_automatic(manager: FallbackManager, models_config: dict):
    """Test automatic chain building when no explicit config."""
    chain = manager.build_chain("gpt-4o", {}, models_config)
    # Should include primary, then same-tier models, then other tiers
    assert chain[0] == "gpt-4o"
    assert "claude-sonnet" in chain or "deepseek-v4" in chain
    assert len(chain) <= 3


def test_build_chain_removes_duplicates(manager: FallbackManager, models_config: dict):
    """Test that duplicate models are removed from chain."""
    explicit_config = {
        "gpt-4o": ["gpt-4o", "claude-sonnet"],  # gpt-4o is duplicate
    }
    chain = manager.build_chain("gpt-4o", explicit_config, models_config)
    assert chain.count("gpt-4o") == 1
    assert "claude-sonnet" in chain


def test_get_stats(manager: FallbackManager):
    """Test get_stats returns correct information."""
    stats = manager.get_stats()
    assert stats["max_attempts"] == 3
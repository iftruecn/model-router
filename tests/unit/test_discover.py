"""
Tests for the model auto-discovery CLI (v1.0.8).

Covers:
- Tier classification heuristics
- Multimodal detection
- Config key generation
- discover_models() with mocked HTTP response
- YAML generation
"""

import pytest
from unittest.mock import patch, MagicMock

from model_router.cli.discover import (
    _classify_tier,
    _detect_multimodal,
    _make_config_key,
    _generate_yaml,
    discover_models,
)


# ------------------------------------------------------------------
# Tier classification
# ------------------------------------------------------------------

class TestClassifyTier:
    """Tests for _classify_tier."""

    def test_flash_models(self):
        assert _classify_tier("gpt-4o-mini") == "flash"
        assert _classify_tier("gemini-2.5-flash") == "flash"
        assert _classify_tier("claude-3-5-haiku") == "flash"
        assert _classify_tier("qwen3-turbo") == "flash"
        assert _classify_tier("mistral-small-lite") == "flash"
        assert _classify_tier("deepseek-v4-flash") == "flash"

    def test_pro_models(self):
        assert _classify_tier("gpt-4o") == "pro"
        assert _classify_tier("claude-sonnet-4") == "pro"
        assert _classify_tier("deepseek-v4-pro") == "pro"
        assert _classify_tier("gemini-2.5-pro") == "pro"
        assert _classify_tier("llama-4-maverick") == "pro"


# ------------------------------------------------------------------
# Multimodal detection
# ------------------------------------------------------------------

class TestDetectMultimodal:
    """Tests for _detect_multimodal."""

    def test_multimodal_models(self):
        assert _detect_multimodal("gpt-4o") is True
        assert _detect_multimodal("gpt-4v") is True
        assert _detect_multimodal("claude-sonnet-4") is True
        assert _detect_multimodal("gemini-2.5-pro") is True
        assert _detect_multimodal("qwen2.5-vl") is True
        assert _detect_multimodal("grok-4") is True

    def test_text_only_models(self):
        assert _detect_multimodal("gpt-4o-mini") is True  # has "4o"
        assert _detect_multimodal("deepseek-v4-pro") is False
        assert _detect_multimodal("qwen3-turbo") is False
        assert _detect_multimodal("mistral-large") is False


# ------------------------------------------------------------------
# Config key generation
# ------------------------------------------------------------------

class TestMakeConfigKey:
    """Tests for _make_config_key."""

    def test_simple(self):
        assert _make_config_key("gpt-4o") == "gpt-4o"

    def test_with_slash(self):
        assert _make_config_key("meta-llama/Llama-4-Maverick") == "meta-llama-llama-4-maverick"

    def test_with_colon(self):
        assert _make_config_key("org:model:v1") == "org-model-v1"


# ------------------------------------------------------------------
# discover_models (mocked HTTP)
# ------------------------------------------------------------------

class TestDiscoverModels:
    """Tests for discover_models with mocked HTTP."""

    def test_discover_success(self):
        """Mock successful model discovery."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
                {"id": "deepseek-chat"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("model_router.cli.discover.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            models = discover_models(
                base_url="https://api.example.com/v1",
                api_key="sk-test",
            )

            assert len(models) == 3
            assert models[0]["id"] == "gpt-4o"
            assert models[0]["tier"] == "pro"
            assert models[1]["id"] == "gpt-4o-mini"
            assert models[1]["tier"] == "flash"
            assert models[2]["id"] == "deepseek-chat"
            assert models[2]["tier"] == "pro"

    def test_discover_empty_list(self):
        """Mock empty model list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        with patch("model_router.cli.discover.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            models = discover_models(
                base_url="https://api.example.com/v1",
                api_key="sk-test",
            )

            assert len(models) == 0


# ------------------------------------------------------------------
# YAML generation
# ------------------------------------------------------------------

class TestGenerateYaml:
    """Tests for _generate_yaml."""

    def test_generate_new(self):
        """Generate YAML for new models."""
        models = [
            {"id": "gpt-4o", "key": "gpt-4o", "name": "gpt-4o",
             "tier": "pro", "multimodal": True,
             "base_url": "https://api.openai.com/v1", "api_key": "sk-test"},
        ]
        yaml_content = _generate_yaml(models, existing_keys=set())
        assert "gpt-4o" in yaml_content
        assert "api.openai.com" in yaml_content

    def test_skip_existing(self):
        """Skip models that already exist in config."""
        models = [
            {"id": "gpt-4o", "key": "gpt-4o", "name": "gpt-4o",
             "tier": "pro", "multimodal": True,
             "base_url": "https://api.openai.com/v1", "api_key": "sk-test"},
        ]
        yaml_content = _generate_yaml(models, existing_keys={"gpt-4o"})
        assert yaml_content == ""
